-- EasyRecon — Pakistan Pharmacy POS Schema (PostgreSQL)
-- Modeled after Oscar, Moneypex, MedicsPK, SadaHisab patterns

CREATE TYPE payment_status AS ENUM ('unpaid', 'partial', 'paid');
CREATE TYPE payment_method AS ENUM ('cash', 'card', 'udhaar', 'jazzcash', 'easypaisa');
CREATE TYPE shift_type AS ENUM ('morning', 'evening', 'night');
CREATE TYPE refund_method AS ENUM ('cash', 'credit');
CREATE TYPE supplier_payment_method AS ENUM ('cash', 'cheque', 'bank_transfer');

CREATE TABLE employees (
    employee_id     SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    role            VARCHAR(30) NOT NULL,  -- owner, pharmacist, cashier
    phone           VARCHAR(20),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE medicines (
    medicine_id     SERIAL PRIMARY KEY,
    name            VARCHAR(150) NOT NULL,
    generic_name    VARCHAR(100),
    category        VARCHAR(50),           -- Tablet, Syrup, Injection, Cream
    manufacturer    VARCHAR(100),
    drap_reg_no     VARCHAR(50),
    unit_type       VARCHAR(20),           -- strip, box, bottle, tablet
    pack_size       INT,
    purchase_price  DECIMAL(10,2),
    retail_price    DECIMAL(10,2),
    requires_rx     BOOLEAN DEFAULT FALSE,
    barcode         VARCHAR(30),
    is_active       BOOLEAN DEFAULT TRUE
);

CREATE TABLE suppliers (
    supplier_id     SERIAL PRIMARY KEY,
    company_name    VARCHAR(150) NOT NULL,
    contact_person  VARCHAR(100),
    phone           VARCHAR(20),
    area            VARCHAR(50),
    payment_terms   INT DEFAULT 30,
    ntn_number      VARCHAR(30),
    strn_number     VARCHAR(30),
    is_active       BOOLEAN DEFAULT TRUE
);

CREATE TABLE customers (
    customer_id     SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    phone           VARCHAR(20),
    area            VARCHAR(50),
    credit_limit    DECIMAL(12,2) DEFAULT 0,
    current_balance DECIMAL(12,2) DEFAULT 0,
    last_purchase   DATE,
    is_active       BOOLEAN DEFAULT TRUE
);

CREATE TABLE stock (
    stock_id            SERIAL PRIMARY KEY,
    medicine_id         INT NOT NULL REFERENCES medicines(medicine_id),
    batch_no            VARCHAR(30) NOT NULL,
    quantity_strips     INT DEFAULT 0,
    quantity_tablets    INT DEFAULT 0,
    purchase_price      DECIMAL(10,2),
    retail_price        DECIMAL(10,2),
    mfg_date            DATE,
    expiry_date         DATE,
    rack_location       VARCHAR(20),
    last_updated        TIMESTAMP DEFAULT NOW(),
    UNIQUE (medicine_id, batch_no)
);

-- Ledger: expected stock from purchases - sales (for reconciliation)
CREATE TABLE stock_ledger (
    ledger_id       SERIAL PRIMARY KEY,
    medicine_id     INT NOT NULL REFERENCES medicines(medicine_id),
    batch_no        VARCHAR(30),
    transaction_type VARCHAR(20),  -- purchase, sale, return, adjustment
    reference_id    INT,
    quantity_change INT NOT NULL,
    balance_after   INT,
    transaction_date TIMESTAMP NOT NULL
);

CREATE TABLE purchases (
    purchase_id     SERIAL PRIMARY KEY,
    supplier_id     INT NOT NULL REFERENCES suppliers(supplier_id),
    invoice_no      VARCHAR(50) NOT NULL,
    purchase_date   DATE NOT NULL,
    total_amount    DECIMAL(12,2),
    discount        DECIMAL(10,2) DEFAULT 0,
    net_amount      DECIMAL(12,2),
    payment_status  payment_status DEFAULT 'unpaid',
    received_by     VARCHAR(50),
    notes           TEXT
);

CREATE TABLE purchase_items (
    item_id         SERIAL PRIMARY KEY,
    purchase_id     INT NOT NULL REFERENCES purchases(purchase_id),
    medicine_id     INT NOT NULL REFERENCES medicines(medicine_id),
    batch_no        VARCHAR(30),
    expiry_date     DATE,
    quantity        INT NOT NULL,
    purchase_price  DECIMAL(10,2),
    retail_price    DECIMAL(10,2),
    amount          DECIMAL(12,2)
);

CREATE TABLE sales (
    sale_id         SERIAL PRIMARY KEY,
    invoice_no      VARCHAR(50) NOT NULL,
    fbr_qr_code     VARCHAR(200),
    sale_date       TIMESTAMP NOT NULL,
    customer_id     INT REFERENCES customers(customer_id),
    cashier_id      INT REFERENCES employees(employee_id),
    subtotal        DECIMAL(12,2),
    discount        DECIMAL(10,2) DEFAULT 0,
    tax_amount      DECIMAL(10,2) DEFAULT 0,
    net_total       DECIMAL(12,2),
    payment_method  payment_method NOT NULL,
    amount_paid     DECIMAL(12,2),
    change_returned DECIMAL(10,2) DEFAULT 0,
    is_return       BOOLEAN DEFAULT FALSE
);

CREATE TABLE sale_items (
    item_id         SERIAL PRIMARY KEY,
    sale_id         INT NOT NULL REFERENCES sales(sale_id),
    medicine_id     INT NOT NULL REFERENCES medicines(medicine_id),
    batch_no        VARCHAR(30),
    quantity        INT NOT NULL,
    unit_type       VARCHAR(20),
    unit_price      DECIMAL(10,2),
    discount        DECIMAL(10,2) DEFAULT 0,
    amount          DECIMAL(12,2)
);

CREATE TABLE cash_register (
    register_id         SERIAL PRIMARY KEY,
    shift_date            DATE NOT NULL,
    shift                 shift_type NOT NULL,
    cashier_id            INT REFERENCES employees(employee_id),
    opening_cash          DECIMAL(12,2),
    total_sales_cash      DECIMAL(12,2),
    total_sales_card      DECIMAL(12,2),
    total_sales_jazz      DECIMAL(12,2),
    total_sales_easypaisa DECIMAL(12,2),
    total_sales_udhaar    DECIMAL(12,2),
    total_returns_cash    DECIMAL(12,2) DEFAULT 0,
    expenses_paid         DECIMAL(12,2) DEFAULT 0,
    closing_cash          DECIMAL(12,2),   -- physically counted
    system_cash           DECIMAL(12,2),   -- expected by POS
    difference            DECIMAL(12,2), -- closing - system
    notes                 TEXT
);

CREATE TABLE supplier_payments (
    payment_id      SERIAL PRIMARY KEY,
    supplier_id     INT NOT NULL REFERENCES suppliers(supplier_id),
    purchase_id     INT REFERENCES purchases(purchase_id),
    payment_date    DATE NOT NULL,
    amount          DECIMAL(12,2),
    payment_method  supplier_payment_method,
    reference_no    VARCHAR(50),
    paid_by         VARCHAR(50),
    notes           TEXT
);

CREATE TABLE returns (
    return_id       SERIAL PRIMARY KEY,
    sale_id         INT REFERENCES sales(sale_id),
    return_date     DATE NOT NULL,
    reason          VARCHAR(200),
    refund_amount   DECIMAL(10,2),
    refund_method   refund_method,
    processed_by    INT REFERENCES employees(employee_id)
);

CREATE TABLE return_items (
    item_id         SERIAL PRIMARY KEY,
    return_id       INT NOT NULL REFERENCES returns(return_id),
    medicine_id     INT NOT NULL REFERENCES medicines(medicine_id),
    batch_no        VARCHAR(30),
    quantity        INT,
    amount          DECIMAL(10,2)
);

CREATE TABLE expenses (
    expense_id      SERIAL PRIMARY KEY,
    expense_date    DATE NOT NULL,
    category        VARCHAR(50),
    description     VARCHAR(200),
    amount          DECIMAL(10,2),
    paid_by         VARCHAR(50),
    register_id     INT REFERENCES cash_register(register_id)
);

-- Seed discrepancies for RAG testing (your system should find these)
CREATE TABLE reconciliation_flags (
    flag_id         SERIAL PRIMARY KEY,
    flag_type       VARCHAR(50) NOT NULL,
    severity        VARCHAR(20),  -- low, medium, high, critical
    entity_table    VARCHAR(50),
    entity_id       INT,
    description     TEXT NOT NULL,
    expected_value  VARCHAR(100),
    actual_value    VARCHAR(100),
    flag_date       DATE,
    is_resolved     BOOLEAN DEFAULT FALSE,
    hidden_answer   TEXT  -- ground truth for eval; remove in production client DBs
);

CREATE INDEX idx_sales_date ON sales(sale_date);
CREATE INDEX idx_sales_payment ON sales(payment_method);
CREATE INDEX idx_stock_expiry ON stock(expiry_date);
CREATE INDEX idx_purchases_supplier ON purchases(supplier_id, purchase_date);
CREATE INDEX idx_cash_register_date ON cash_register(shift_date);
CREATE INDEX idx_customers_balance ON customers(current_balance);
