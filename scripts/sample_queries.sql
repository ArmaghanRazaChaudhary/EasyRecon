-- Sample reconciliation queries for EasyRecon RAG testing
-- Run against: data/bismillah_pharmacy.db

-- 1. Cash shorts (last 30 days)
SELECT shift_date, shift, cashier_id, system_cash, closing_cash, difference, notes
FROM cash_register
WHERE difference < -500
  AND shift_date >= date('now', '-30 days')
ORDER BY difference ASC;

-- 2. Unpaid supplier invoices older than 30 days
SELECT p.purchase_id, s.company_name, p.invoice_no, p.purchase_date, p.net_amount, p.payment_status
FROM purchases p
JOIN suppliers s ON s.supplier_id = p.supplier_id
WHERE p.payment_status != 'paid'
  AND julianday('now') - julianday(p.purchase_date) > 30
ORDER BY p.purchase_date;

-- 3. Stock vs ledger mismatch
SELECT st.medicine_id, m.name, st.batch_no,
       st.quantity_strips AS stock_qty,
       sl.balance_after AS ledger_qty,
       (st.quantity_strips - sl.balance_after) AS difference
FROM stock st
JOIN medicines m ON m.medicine_id = st.medicine_id
JOIN (
    SELECT medicine_id, batch_no, balance_after,
           ROW_NUMBER() OVER (PARTITION BY medicine_id, batch_no ORDER BY ledger_id DESC) AS rn
    FROM stock_ledger
) sl ON sl.medicine_id = st.medicine_id AND sl.batch_no = st.batch_no AND sl.rn = 1
WHERE st.quantity_strips != sl.balance_after;

-- 4. Duplicate supplier payments (same purchase_id)
SELECT purchase_id, COUNT(*) AS payment_count, SUM(amount) AS total_paid
FROM supplier_payments
GROUP BY purchase_id
HAVING COUNT(*) > 1;

-- 5. Credit customers over limit
SELECT name, phone, current_balance, credit_limit,
       (current_balance - credit_limit) AS over_by
FROM customers
WHERE credit_limit > 0 AND current_balance > credit_limit
ORDER BY over_by DESC;

-- 6. Expired stock still on hand
SELECT m.name, st.batch_no, st.quantity_strips, st.expiry_date
FROM stock st
JOIN medicines m ON m.medicine_id = st.medicine_id
WHERE st.expiry_date < date('now') AND st.quantity_strips > 0
ORDER BY st.expiry_date;

-- 7. Sales missing FBR QR
SELECT sale_id, invoice_no, sale_date, net_total
FROM sales
WHERE fbr_qr_code IS NULL OR fbr_qr_code = ''
ORDER BY sale_date DESC;

-- 8. Daily sales summary by payment method
SELECT date(sale_date) AS day,
       payment_method,
       COUNT(*) AS invoices,
       ROUND(SUM(net_total), 2) AS total
FROM sales
GROUP BY date(sale_date), payment_method
ORDER BY day DESC, total DESC;

-- 9. Top stock-loss candidates (negative ledger drift)
SELECT m.name, st.batch_no, st.quantity_strips,
       julianday(st.expiry_date) - julianday('now') AS days_to_expiry
FROM stock st
JOIN medicines m ON m.medicine_id = st.medicine_id
WHERE st.quantity_strips BETWEEN 1 AND 5
ORDER BY days_to_expiry ASC
LIMIT 20;

-- 10. Ground truth flags (eval only — hide from production clients)
SELECT flag_type, severity, description, hidden_answer
FROM reconciliation_flags
WHERE is_resolved = 0
ORDER BY
  CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END;
