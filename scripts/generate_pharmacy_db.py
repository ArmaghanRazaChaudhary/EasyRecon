#!/usr/bin/env python3
"""
Generate a realistic Pakistan pharmacy database for EasyRecon RAG testing.

Usage:
  python scripts/generate_pharmacy_db.py
  python scripts/generate_pharmacy_db.py --months 12 --scale large
  python scripts/generate_pharmacy_db.py --output data/bismillah_pharmacy.db
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import string
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# ---------------------------------------------------------------------------
# Pakistani pharmacy seed data
# ---------------------------------------------------------------------------

PHARMACY_NAME = "Bismillah Medical Store"
PHARMACY_CITY = "Lahore"

MANUFACTURERS = [
    "GSK Pakistan", "Getz Pharma", "Searle Pakistan", "Highnoon Laboratories",
    "Martin Dow", "Abbott Pakistan", "Sanofi Pakistan", "Pfizer Pakistan",
    "Hilton Pharma", "Barrett Hodgson", "Atco Laboratories", "Wilson's Pharma",
    "Pharmevo", "Sami Pharma", "Genix Pharma", "Ferozsons Laboratories",
    "OBS Pakistan", "Zafa Pharmaceutical", "Bosch Pharma", "Brookes Pharma",
]

SUPPLIER_NAMES = [
    "M/S Allied Traders", "M/S Zafa Distributors", "M/S Punjab Medical Co",
    "M/S Karachi Pharma Supply", "M/S Lahore Drug House", "M/S Medilink Distributors",
    "M/S Fazal Din & Sons", "M/S Shaheen Medical Store Wholesale",
    "M/S Al-Shifa Traders", "M/S Hamdard Distributors", "M/S Crescent Pharma Supply",
    "M/S Pak Medical Corporation", "M/S Green Pharma Lahore", "M/S City Drug House",
    "M/S National Medical Store", "M/S Metro Pharma Distributors", "M/S Care Plus Supply",
    "M/S Health Line Traders", "M/S Prime Medical Co", "M/S United Drug House",
    "M/S Al-Hamd Traders", "M/S Noor Medical Supply", "M/S Royal Pharma Lahore",
    "M/S Galaxy Distributors", "M/S Trust Medical Co", "M/S Alpha Pharma Supply",
    "M/S Beta Drug House", "M/S Care Medical Traders", "M/S Delta Pharma",
    "M/S Omega Medical Wholesale",
]

LAHORE_AREAS = [
    "Gulberg", "Model Town", "Johar Town", "DHA", "Garden Town", "Ichhra",
    "Faisal Town", "Township", "Bahria Town", "Cantt", "Shadman", "Samanabad",
    "Allama Iqbal Town", "Wapda Town", "Valencia", "Askari", "Defence",
]

MEDICINES = [
    ("Panadol 500mg", "Paracetamol", "Tablet", "GSK Pakistan", "strip", 10, 45, 55, False),
    ("Panadol Extra", "Paracetamol+Caffeine", "Tablet", "GSK Pakistan", "strip", 10, 65, 80, False),
    ("Brufen 400mg", "Ibuprofen", "Tablet", "Abbott Pakistan", "strip", 10, 85, 110, False),
    ("Disprin", "Aspirin", "Tablet", "Reckitt", "strip", 10, 25, 35, False),
    ("Augmentin 625mg", "Amoxicillin+Clavulanate", "Tablet", "GSK Pakistan", "strip", 6, 380, 450, True),
    ("Flagyl 400mg", "Metronidazole", "Tablet", "Sanofi Pakistan", "strip", 10, 95, 120, True),
    ("Ciprofloxacin 500mg", "Ciprofloxacin", "Tablet", "Martin Dow", "strip", 10, 120, 150, True),
    ("Azomax 500mg", "Azithromycin", "Tablet", "Pfizer Pakistan", "strip", 3, 420, 520, True),
    ("Risek 20mg", "Omeprazole", "Capsule", "Getz Pharma", "strip", 14, 280, 350, False),
    ("Nexum 40mg", "Esomeprazole", "Capsule", "Getz Pharma", "strip", 14, 450, 550, False),
    ("Concor 5mg", "Bisoprolol", "Tablet", "Merck", "strip", 10, 320, 400, True),
    ("Norvasc 5mg", "Amlodipine", "Tablet", "Pfizer Pakistan", "strip", 10, 380, 470, True),
    ("Glucophage 500mg", "Metformin", "Tablet", "Merck", "strip", 10, 55, 70, True),
    ("Amaryl 2mg", "Glimepiride", "Tablet", "Sanofi Pakistan", "strip", 10, 180, 230, True),
    ("Lipitor 10mg", "Atorvastatin", "Tablet", "Pfizer Pakistan", "strip", 10, 520, 650, True),
    ("Ventolin Inhaler", "Salbutamol", "Inhaler", "GSK Pakistan", "piece", 1, 450, 580, True),
    ("Seretide 250", "Fluticasone+Salmeterol", "Inhaler", "GSK Pakistan", "piece", 1, 1850, 2200, True),
    ("Zyrtec 10mg", "Cetirizine", "Tablet", "UCB", "strip", 10, 95, 120, False),
    ("Avil 25mg", "Pheniramine", "Tablet", "Sanofi Pakistan", "strip", 10, 35, 45, False),
    ("Ponstan 500mg", "Mefenamic Acid", "Tablet", "Pfizer Pakistan", "strip", 10, 120, 150, False),
    ("Volini Gel", "Diclofenac", "Gel", "Sanofi Pakistan", "tube", 1, 280, 350, False),
    ("Voren 50mg", "Diclofenac", "Tablet", "Barrett Hodgson", "strip", 10, 65, 85, False),
    ("Calpol Syrup", "Paracetamol", "Syrup", "GSK Pakistan", "bottle", 1, 95, 120, False),
    ("Arinac Forte", "Ibuprofen+Pseudoephedrine", "Tablet", "Abbott Pakistan", "strip", 10, 75, 95, False),
    ("Sinarest", "Paracetamol+Phenylephrine", "Tablet", "Centaur", "strip", 10, 55, 70, False),
    ("Strepsils", "Antiseptic Lozenge", "Lozenge", "Reckitt", "strip", 8, 180, 220, False),
    ("Hydryllin DM", "Dextromethorphan", "Syrup", "Searle Pakistan", "bottle", 1, 120, 150, False),
    ("Actifed", "Triprolidine+Pseudoephedrine", "Syrup", "GSK Pakistan", "bottle", 1, 145, 180, False),
    ("Gravinate", "Dimenhydrinate", "Tablet", "Searle Pakistan", "strip", 10, 45, 58, False),
    ("Motilium 10mg", "Domperidone", "Tablet", "Janssen", "strip", 10, 180, 230, False),
    ("Imodium", "Loperamide", "Capsule", "Janssen", "strip", 6, 220, 280, False),
    ("Entamizole", "Diloxanide+Metronidazole", "Tablet", "Searle Pakistan", "strip", 10, 85, 110, True),
    ("Velosef 500mg", "Cephalexin", "Capsule", "GSK Pakistan", "strip", 10, 280, 350, True),
    ("Klaricid 500mg", "Clarithromycin", "Tablet", "Abbott Pakistan", "strip", 10, 650, 800, True),
    ("Zinnat 500mg", "Cefuroxime", "Tablet", "GSK Pakistan", "strip", 10, 720, 890, True),
    ("Telfast 120mg", "Fexofenadine", "Tablet", "Sanofi Pakistan", "strip", 10, 380, 470, False),
    ("Montiget 10mg", "Montelukast", "Tablet", "Getz Pharma", "strip", 10, 420, 520, True),
    ("Singulair 10mg", "Montelukast", "Tablet", "MSD", "strip", 10, 850, 1050, True),
    ("Deltacortril 5mg", "Prednisolone", "Tablet", "Pfizer Pakistan", "strip", 10, 45, 58, True),
    ("Hydrocort 1%", "Hydrocortisone", "Cream", "GSK Pakistan", "tube", 1, 65, 85, False),
    ("Betnovate N", "Betamethasone+Neomycin", "Cream", "GSK Pakistan", "tube", 1, 95, 120, True),
    ("Clotrimazole Cream", "Clotrimazole", "Cream", "Martin Dow", "tube", 1, 55, 70, False),
    ("Canesten", "Clotrimazole", "Cream", "Bayer", "tube", 1, 180, 220, False),
    ("Fucidin Cream", "Fusidic Acid", "Cream", "Leo Pharma", "tube", 1, 320, 400, True),
    ("Polyfax Ointment", "Bacitracin+Polymyxin", "Ointment", "GSK Pakistan", "tube", 1, 85, 110, False),
    ("Omnipaque Injection", "Iohexol", "Injection", "GE Healthcare", "vial", 1, 4500, 5200, True),
    ("Insulin Mixtard", "Insulin", "Injection", "Novo Nordisk", "vial", 1, 1850, 2200, True),
    ("Humalog", "Insulin Lispro", "Injection", "Eli Lilly", "vial", 1, 4200, 5000, True),
    ("Ecosprin 75mg", "Aspirin", "Tablet", "USV", "strip", 14, 35, 45, False),
    ("Plavix 75mg", "Clopidogrel", "Tablet", "Sanofi Pakistan", "strip", 10, 850, 1050, True),
]

# Extend medicine list programmatically with variants
EXTRA_GENERICS = [
    ("Metronidazole", "Tablet", 10), ("Cefixime", "Tablet", 10), ("Levofloxacin", "Tablet", 10),
    ("Losartan", "Tablet", 10), ("Atenolol", "Tablet", 10), ("Hydrochlorothiazide", "Tablet", 10),
    ("Amlodipine", "Tablet", 10), ("Glibenclamide", "Tablet", 10), ("Sitagliptin", "Tablet", 10),
    ("Pantoprazole", "Tablet", 10), ("Ranitidine", "Tablet", 10), ("Domperidone", "Tablet", 10),
    ("Ondansetron", "Tablet", 10), ("Tramadol", "Capsule", 10), ("Codeine", "Syrup", 1),
    ("Salbutamol", "Syrup", 1), ("Ambroxol", "Syrup", 1), ("Iron Supplement", "Syrup", 1),
    ("Calcium", "Tablet", 10), ("Vitamin D3", "Capsule", 10), ("Multivitamin", "Tablet", 10),
    ("ORS Sachet", "Sachet", 1), ("Zinc", "Tablet", 10), ("Folic Acid", "Tablet", 10),
    ("Albendazole", "Tablet", 1), ("Mebendazole", "Tablet", 1), ("Fluconazole", "Capsule", 4),
    ("Acyclovir", "Tablet", 10), ("Allopurinol", "Tablet", 10), ("Colchicine", "Tablet", 10),
]

EMPLOYEES = [
    ("Ahmed Hassan", "owner"),
    ("Dr. Fatima Khan", "pharmacist"),
    ("Usman Ali", "cashier"),
    ("Bilal Ahmed", "cashier"),
    ("Sana Malik", "cashier"),
    ("Imran Sheikh", "cashier"),
]

PAYMENT_METHODS = ["cash", "card", "udhaar", "jazzcash", "easypaisa"]
SHIFTS = ["morning", "evening", "night"]
EXPENSE_CATEGORIES = ["rent", "salary", "electricity", "gas", "internet", "cleaning", "misc"]


@dataclass
class ScaleConfig:
    months: int
    medicines_extra: int
    customers: int
    daily_sales_min: int
    daily_sales_max: int
    purchases_per_week: int


SCALES = {
    "small": ScaleConfig(6, 50, 40, 40, 70, 8),
    "medium": ScaleConfig(9, 120, 80, 70, 120, 12),
    "large": ScaleConfig(12, 200, 120, 90, 160, 18),
    "xlarge": ScaleConfig(18, 300, 200, 120, 200, 25),
}


def money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def random_phone() -> str:
    return f"03{random.randint(0, 9)}{random.randint(10000000, 99999999)}"


def random_ntn() -> str:
    return f"{random.randint(1000000, 9999999)}-{random.randint(1, 9)}"


def random_batch() -> str:
    return f"BN-{random.randint(2023, 2025)}-{random.randint(1000, 9999)}"


def random_drap_reg() -> str:
    return f"DRAP-{random.randint(10000, 99999)}-{random.choice(string.ascii_uppercase)}"


def fbr_invoice_no(d: date, seq: int) -> str:
    return f"FBR-{d.strftime('%Y%m%d')}-{seq:05d}"


def fbr_qr_placeholder(invoice_no: str, amount: Decimal) -> str:
    return f"FBR|{invoice_no}|{amount}|{PHARMACY_NAME}|{PHARMACY_CITY}"


def build_medicine_catalog(extra_count: int) -> list[tuple]:
    catalog = list(MEDICINES)
    used_names = {m[0] for m in catalog}

    for generic, category, pack_size in EXTRA_GENERICS:
        mfr = random.choice(MANUFACTURERS)
        strength = random.choice(["250mg", "500mg", "5mg", "10mg", "20mg", ""])
        name = f"{generic.split()[0]} {strength}".strip()
        if name in used_names:
            name = f"{mfr.split()[0]} {generic.split()[0]} {strength}".strip()
        if name in used_names:
            continue
        used_names.add(name)
        purchase = random.randint(30, 800)
        retail = int(purchase * random.uniform(1.15, 1.45))
        requires_rx = generic in {
            "Tramadol", "Codeine", "Insulin", "Cefixime", "Levofloxacin",
            "Sitagliptin", "Fluconazole", "Acyclovir", "Losartan",
        }
        unit = "strip" if category in ("Tablet", "Capsule") else (
            "bottle" if category == "Syrup" else "piece"
        )
        catalog.append((name, generic, category, mfr, unit, pack_size, purchase, retail, requires_rx))

    # Random branded variants until we hit target
    while len(catalog) < len(MEDICINES) + extra_count:
        generic = random.choice([g[0] for g in EXTRA_GENERICS])
        mfr = random.choice(MANUFACTURERS)
        category = random.choice(["Tablet", "Capsule", "Syrup", "Cream", "Injection"])
        strength = random.choice(["250mg", "500mg", "5mg", "10mg", ""])
        name = f"{mfr.split()[0]}-{generic.split()[0]}-{strength}".replace("--", "-")
        if name in used_names:
            continue
        used_names.add(name)
        pack_size = random.choice([1, 6, 10, 14, 20])
        purchase = random.randint(25, 1200)
        retail = int(purchase * random.uniform(1.12, 1.5))
        unit = "strip" if category in ("Tablet", "Capsule") else "piece"
        catalog.append((name, generic, category, mfr, unit, pack_size, purchase, retail, random.random() < 0.25))

    return catalog


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE employees (
            employee_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            phone TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE medicines (
            medicine_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            generic_name TEXT,
            category TEXT,
            manufacturer TEXT,
            drap_reg_no TEXT,
            unit_type TEXT,
            pack_size INTEGER,
            purchase_price REAL,
            retail_price REAL,
            requires_rx INTEGER DEFAULT 0,
            barcode TEXT,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE suppliers (
            supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            contact_person TEXT,
            phone TEXT,
            area TEXT,
            payment_terms INTEGER DEFAULT 30,
            ntn_number TEXT,
            strn_number TEXT,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            area TEXT,
            credit_limit REAL DEFAULT 0,
            current_balance REAL DEFAULT 0,
            last_purchase TEXT,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE stock (
            stock_id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            batch_no TEXT NOT NULL,
            quantity_strips INTEGER DEFAULT 0,
            quantity_tablets INTEGER DEFAULT 0,
            purchase_price REAL,
            retail_price REAL,
            mfg_date TEXT,
            expiry_date TEXT,
            rack_location TEXT,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (medicine_id) REFERENCES medicines(medicine_id),
            UNIQUE (medicine_id, batch_no)
        );

        CREATE TABLE stock_ledger (
            ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            batch_no TEXT,
            transaction_type TEXT,
            reference_id INTEGER,
            quantity_change INTEGER NOT NULL,
            balance_after INTEGER,
            transaction_date TEXT NOT NULL,
            FOREIGN KEY (medicine_id) REFERENCES medicines(medicine_id)
        );

        CREATE TABLE purchases (
            purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            invoice_no TEXT NOT NULL,
            purchase_date TEXT NOT NULL,
            total_amount REAL,
            discount REAL DEFAULT 0,
            net_amount REAL,
            payment_status TEXT DEFAULT 'unpaid',
            received_by TEXT,
            notes TEXT,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
        );

        CREATE TABLE purchase_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_id INTEGER NOT NULL,
            medicine_id INTEGER NOT NULL,
            batch_no TEXT,
            expiry_date TEXT,
            quantity INTEGER NOT NULL,
            purchase_price REAL,
            retail_price REAL,
            amount REAL,
            FOREIGN KEY (purchase_id) REFERENCES purchases(purchase_id),
            FOREIGN KEY (medicine_id) REFERENCES medicines(medicine_id)
        );

        CREATE TABLE sales (
            sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT NOT NULL,
            fbr_qr_code TEXT,
            sale_date TEXT NOT NULL,
            customer_id INTEGER,
            cashier_id INTEGER,
            subtotal REAL,
            discount REAL DEFAULT 0,
            tax_amount REAL DEFAULT 0,
            net_total REAL,
            payment_method TEXT NOT NULL,
            amount_paid REAL,
            change_returned REAL DEFAULT 0,
            is_return INTEGER DEFAULT 0,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
            FOREIGN KEY (cashier_id) REFERENCES employees(employee_id)
        );

        CREATE TABLE sale_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            medicine_id INTEGER NOT NULL,
            batch_no TEXT,
            quantity INTEGER NOT NULL,
            unit_type TEXT,
            unit_price REAL,
            discount REAL DEFAULT 0,
            amount REAL,
            FOREIGN KEY (sale_id) REFERENCES sales(sale_id),
            FOREIGN KEY (medicine_id) REFERENCES medicines(medicine_id)
        );

        CREATE TABLE cash_register (
            register_id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_date TEXT NOT NULL,
            shift TEXT NOT NULL,
            cashier_id INTEGER,
            opening_cash REAL,
            total_sales_cash REAL,
            total_sales_card REAL,
            total_sales_jazz REAL,
            total_sales_easypaisa REAL,
            total_sales_udhaar REAL,
            total_returns_cash REAL DEFAULT 0,
            expenses_paid REAL DEFAULT 0,
            closing_cash REAL,
            system_cash REAL,
            difference REAL,
            notes TEXT,
            FOREIGN KEY (cashier_id) REFERENCES employees(employee_id)
        );

        CREATE TABLE supplier_payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            purchase_id INTEGER,
            payment_date TEXT NOT NULL,
            amount REAL,
            payment_method TEXT,
            reference_no TEXT,
            paid_by TEXT,
            notes TEXT,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
            FOREIGN KEY (purchase_id) REFERENCES purchases(purchase_id)
        );

        CREATE TABLE returns (
            return_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER,
            return_date TEXT NOT NULL,
            reason TEXT,
            refund_amount REAL,
            refund_method TEXT,
            processed_by INTEGER,
            FOREIGN KEY (sale_id) REFERENCES sales(sale_id),
            FOREIGN KEY (processed_by) REFERENCES employees(employee_id)
        );

        CREATE TABLE return_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_id INTEGER NOT NULL,
            medicine_id INTEGER NOT NULL,
            batch_no TEXT,
            quantity INTEGER,
            amount REAL,
            FOREIGN KEY (return_id) REFERENCES returns(return_id),
            FOREIGN KEY (medicine_id) REFERENCES medicines(medicine_id)
        );

        CREATE TABLE expenses (
            expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_date TEXT NOT NULL,
            category TEXT,
            description TEXT,
            amount REAL,
            paid_by TEXT,
            register_id INTEGER,
            FOREIGN KEY (register_id) REFERENCES cash_register(register_id)
        );

        CREATE TABLE reconciliation_flags (
            flag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            flag_type TEXT NOT NULL,
            severity TEXT,
            entity_table TEXT,
            entity_id INTEGER,
            description TEXT NOT NULL,
            expected_value TEXT,
            actual_value TEXT,
            flag_date TEXT,
            is_resolved INTEGER DEFAULT 0,
            hidden_answer TEXT
        );

        CREATE INDEX idx_sales_date ON sales(sale_date);
        CREATE INDEX idx_sales_payment ON sales(payment_method);
        CREATE INDEX idx_stock_expiry ON stock(expiry_date);
        CREATE INDEX idx_purchases_supplier ON purchases(supplier_id, purchase_date);
        CREATE INDEX idx_cash_register_date ON cash_register(shift_date);
        CREATE INDEX idx_customers_balance ON customers(current_balance);
        """
    )


class PharmacyGenerator:
    def __init__(self, conn: sqlite3.Connection, config: ScaleConfig, seed: int = 42):
        self.conn = conn
        self.config = config
        random.seed(seed)
        self.start_date = date.today() - timedelta(days=config.months * 30)
        self.end_date = date.today()
        self.medicine_ids: list[int] = []
        self.medicine_meta: dict[int, tuple] = {}
        self.supplier_ids: list[int] = []
        self.customer_ids: list[int] = []
        self.cashier_ids: list[int] = []
        self.stock_batches: dict[int, list[dict]] = defaultdict(list)
        self.ledger_balance: dict[tuple[int, str], int] = defaultdict(int)
        self.purchase_records: list[dict] = []
        self.sale_records: list[dict] = []
        self.flags: list[dict] = []
        self.invoice_counter = 1

    def log(self, msg: str) -> None:
        print(msg)

    def insert_employees(self) -> None:
        for name, role in EMPLOYEES:
            cur = self.conn.execute(
                "INSERT INTO employees (name, role, phone) VALUES (?, ?, ?)",
                (name, role, random_phone()),
            )
            eid = cur.lastrowid
            if role == "cashier":
                self.cashier_ids.append(eid)

    def insert_medicines(self) -> None:
        catalog = build_medicine_catalog(self.config.medicines_extra)
        for row in catalog:
            name, generic, category, mfr, unit, pack, purchase, retail, rx = row
            cur = self.conn.execute(
                """
                INSERT INTO medicines
                (name, generic_name, category, manufacturer, drap_reg_no, unit_type,
                 pack_size, purchase_price, retail_price, requires_rx, barcode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name, generic, category, mfr, random_drap_reg(), unit, pack,
                    float(purchase), float(retail), int(rx),
                    f"890{random.randint(100000000, 999999999)}",
                ),
            )
            mid = cur.lastrowid
            self.medicine_ids.append(mid)
            self.medicine_meta[mid] = row

    def insert_suppliers(self) -> None:
        for company in SUPPLIER_NAMES:
            cur = self.conn.execute(
                """
                INSERT INTO suppliers
                (company_name, contact_person, phone, area, payment_terms, ntn_number, strn_number)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company,
                    f"M/S {random.choice(['Muhammad', 'Ali', 'Hassan', 'Khalid', 'Asif'])}",
                    random_phone(),
                    random.choice(LAHORE_AREAS + ["Karachi", "Islamabad", "Faisalabad"]),
                    random.choice([15, 30, 45, 60]),
                    random_ntn(),
                    random_ntn(),
                ),
            )
            self.supplier_ids.append(cur.lastrowid)

    def insert_customers(self) -> None:
        first_names = ["Muhammad", "Ahmed", "Ali", "Hassan", "Usman", "Bilal", "Imran", "Sana", "Ayesha", "Fatima"]
        last_names = ["Khan", "Sheikh", "Malik", "Butt", "Raza", "Hussain", "Iqbal", "Chaudhry", "Mirza", "Ansari"]
        for i in range(self.config.customers):
            name = f"{random.choice(first_names)} {random.choice(last_names)}"
            credit_limit = random.choice([0, 0, 0, 5000, 10000, 15000, 25000])
            cur = self.conn.execute(
                """
                INSERT INTO customers (name, phone, area, credit_limit, current_balance)
                VALUES (?, ?, ?, ?, 0)
                """,
                (name, random_phone(), random.choice(LAHORE_AREAS), credit_limit),
            )
            self.customer_ids.append(cur.lastrowid)

    def add_ledger(self, medicine_id: int, batch_no: str, tx_type: str, ref_id: int, qty: int, when: datetime) -> None:
        key = (medicine_id, batch_no)
        self.ledger_balance[key] += qty
        self.conn.execute(
            """
            INSERT INTO stock_ledger
            (medicine_id, batch_no, transaction_type, reference_id, quantity_change, balance_after, transaction_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (medicine_id, batch_no, tx_type, ref_id, qty, self.ledger_balance[key], when.isoformat()),
        )

    def generate_initial_stock_and_purchases(self) -> None:
        """Seed inventory via historical purchases from start_date."""
        d = self.start_date
        purchase_id_seq = 1
        while d <= self.end_date:
            if d.weekday() in (0, 2, 4):  # Mon/Wed/Fri purchasing rhythm
                for _ in range(random.randint(1, 3)):
                    self._create_purchase(d, purchase_id_seq)
                    purchase_id_seq += 1
            d += timedelta(days=1)

    def _create_purchase(self, purchase_date: date, seq: int, forced_supplier: int | None = None) -> int:
        supplier_id = forced_supplier or random.choice(self.supplier_ids)
        items_count = random.randint(3, 12)
        chosen_meds = random.sample(self.medicine_ids, min(items_count, len(self.medicine_ids)))

        line_items = []
        total = Decimal("0")
        for med_id in chosen_meds:
            _, _, _, _, unit, pack, purchase, retail, _ = self.medicine_meta[med_id]
            qty = random.randint(5, 80)
            price = money(purchase)
            amount = money(float(price) * qty)
            total += amount
            batch = random_batch()
            mfg = purchase_date - timedelta(days=random.randint(30, 400))
            expiry = mfg + timedelta(days=random.randint(365, 900))
            line_items.append({
                "medicine_id": med_id,
                "batch_no": batch,
                "expiry_date": expiry,
                "quantity": qty,
                "purchase_price": float(price),
                "retail_price": float(retail),
                "amount": float(amount),
            })

        discount = money(float(total) * random.uniform(0, 0.05))
        net = money(float(total) - float(discount))
        invoice_no = f"SUP-{purchase_date.strftime('%Y%m')}-{seq:04d}-{supplier_id}"

        cur = self.conn.execute(
            """
            INSERT INTO purchases
            (supplier_id, invoice_no, purchase_date, total_amount, discount, net_amount, payment_status, received_by)
            VALUES (?, ?, ?, ?, ?, ?, 'unpaid', ?)
            """,
            (
                supplier_id, invoice_no, purchase_date.isoformat(),
                float(total), float(discount), float(net),
                random.choice(["Usman Ali", "Bilal Ahmed", "Imran Sheikh"]),
            ),
        )
        purchase_id = cur.lastrowid

        for item in line_items:
            self.conn.execute(
                """
                INSERT INTO purchase_items
                (purchase_id, medicine_id, batch_no, expiry_date, quantity, purchase_price, retail_price, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    purchase_id, item["medicine_id"], item["batch_no"], item["expiry_date"].isoformat(),
                    item["quantity"], item["purchase_price"], item["retail_price"], item["amount"],
                ),
            )
            # Update stock table
            med_id = item["medicine_id"]
            batch = item["batch_no"]
            existing = self.conn.execute(
                "SELECT stock_id, quantity_strips FROM stock WHERE medicine_id=? AND batch_no=?",
                (med_id, batch),
            ).fetchone()
            if existing:
                new_qty = existing[1] + item["quantity"]
                self.conn.execute(
                    "UPDATE stock SET quantity_strips=?, last_updated=? WHERE stock_id=?",
                    (new_qty, datetime.combine(purchase_date, datetime.min.time()).isoformat(), existing[0]),
                )
            else:
                mfg = item["expiry_date"] - timedelta(days=random.randint(365, 900))
                self.conn.execute(
                    """
                    INSERT INTO stock
                    (medicine_id, batch_no, quantity_strips, purchase_price, retail_price, mfg_date, expiry_date, rack_location)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        med_id, batch, item["quantity"], item["purchase_price"], item["retail_price"],
                        mfg.isoformat(), item["expiry_date"].isoformat(),
                        f"{random.choice('ABCDEFGHIJ')}{random.randint(1, 12)}",
                    ),
                )
                self.stock_batches[med_id].append({"batch_no": batch, "expiry": item["expiry_date"]})

            self.add_ledger(
                med_id, batch, "purchase", purchase_id, item["quantity"],
                datetime.combine(purchase_date, datetime.min.time().replace(hour=10)),
            )

        record = {
            "purchase_id": purchase_id,
            "supplier_id": supplier_id,
            "purchase_date": purchase_date,
            "net_amount": float(net),
            "payment_status": "unpaid",
        }
        self.purchase_records.append(record)
        return purchase_id

    def _pick_batch(self, medicine_id: int) -> tuple[str, date] | None:
        rows = self.conn.execute(
            "SELECT batch_no, expiry_date, quantity_strips FROM stock WHERE medicine_id=? AND quantity_strips > 0",
            (medicine_id,),
        ).fetchall()
        if not rows:
            return None
        batch_no, expiry, qty = random.choice(rows)
        return batch_no, date.fromisoformat(expiry)

    def generate_sales(self) -> None:
        d = self.start_date
        daily_seq = defaultdict(int)
        while d <= self.end_date:
            if d.weekday() == 6:  # Sunday slightly slower
                n_sales = random.randint(self.config.daily_sales_min // 2, self.config.daily_sales_max // 2)
            else:
                n_sales = random.randint(self.config.daily_sales_min, self.config.daily_sales_max)

            for _ in range(n_sales):
                hour = random.choices(
                    range(8, 23),
                    weights=[1, 2, 3, 4, 5, 6, 8, 10, 12, 10, 8, 6, 5, 4, 3],
                    k=1,
                )[0]
                minute = random.randint(0, 59)
                sale_dt = datetime.combine(d, datetime.min.time().replace(hour=hour, minute=minute))
                self._create_sale(sale_dt, daily_seq[d])
                daily_seq[d] += 1
            d += timedelta(days=1)

    def _create_sale(self, sale_dt: datetime, seq: int) -> int:
        cashier_id = random.choice(self.cashier_ids)
        items_count = random.choices([1, 2, 3, 4, 5], weights=[30, 35, 20, 10, 5])[0]
        chosen = random.sample(self.medicine_ids, min(items_count, len(self.medicine_ids)))

        line_items = []
        subtotal = Decimal("0")
        for med_id in chosen:
            picked = self._pick_batch(med_id)
            if not picked:
                continue
            batch_no, _ = picked
            _, _, _, _, unit, _, _, retail, _ = self.medicine_meta[med_id]
            qty = random.randint(1, 3)
            unit_price = money(retail)
            disc = money(float(unit_price) * qty * random.uniform(0, 0.08))
            amount = money(float(unit_price) * qty - float(disc))
            subtotal += amount
            line_items.append({
                "medicine_id": med_id,
                "batch_no": batch_no,
                "quantity": qty,
                "unit_type": unit,
                "unit_price": float(unit_price),
                "discount": float(disc),
                "amount": float(amount),
            })

        if not line_items:
            return 0

        invoice_discount = money(float(subtotal) * random.uniform(0, 0.03))
        subtotal_after = money(float(subtotal) - float(invoice_discount))
        tax = money(float(subtotal_after) * 0.0)  # most small pharmacies show 0 or minimal
        net = money(float(subtotal_after) + float(tax))

        payment_weights = [55, 10, 15, 10, 10]
        payment_method = random.choices(PAYMENT_METHODS, weights=payment_weights)[0]

        customer_id = None
        if payment_method == "udhaar":
            credit_customers = [
                cid for cid in self.customer_ids
                if self.conn.execute("SELECT credit_limit FROM customers WHERE customer_id=?", (cid,)).fetchone()[0] > 0
            ]
            if credit_customers:
                customer_id = random.choice(credit_customers)

        amount_paid = float(net)
        change = 0.0
        if payment_method == "cash":
            amount_paid = float(money(float(net) + random.choice([0, 0, 0, 50, 100, 500])))
            change = money(amount_paid - float(net))
            amount_paid = float(net) if change < 0 else amount_paid
            change = max(0, float(change))

        invoice_no = fbr_invoice_no(sale_dt.date(), self.invoice_counter)
        self.invoice_counter += 1
        fbr_qr = fbr_qr_placeholder(invoice_no, net)

        cur = self.conn.execute(
            """
            INSERT INTO sales
            (invoice_no, fbr_qr_code, sale_date, customer_id, cashier_id, subtotal, discount,
             tax_amount, net_total, payment_method, amount_paid, change_returned)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_no, fbr_qr, sale_dt.isoformat(), customer_id, cashier_id,
                float(subtotal), float(invoice_discount), float(tax), float(net),
                payment_method, amount_paid, change,
            ),
        )
        sale_id = cur.lastrowid

        for item in line_items:
            self.conn.execute(
                """
                INSERT INTO sale_items
                (sale_id, medicine_id, batch_no, quantity, unit_type, unit_price, discount, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sale_id, item["medicine_id"], item["batch_no"], item["quantity"],
                    item["unit_type"], item["unit_price"], item["discount"], item["amount"],
                ),
            )
            # Decrement stock
            self.conn.execute(
                """
                UPDATE stock SET quantity_strips = MAX(0, quantity_strips - ?), last_updated=?
                WHERE medicine_id=? AND batch_no=?
                """,
                (item["quantity"], sale_dt.isoformat(), item["medicine_id"], item["batch_no"]),
            )
            self.add_ledger(
                item["medicine_id"], item["batch_no"], "sale", sale_id, -item["quantity"], sale_dt,
            )

        if payment_method == "udhaar" and customer_id:
            self.conn.execute(
                "UPDATE customers SET current_balance = current_balance + ?, last_purchase=? WHERE customer_id=?",
                (float(net), sale_dt.date().isoformat(), customer_id),
            )

        self.sale_records.append({
            "sale_id": sale_id,
            "sale_date": sale_dt,
            "payment_method": payment_method,
            "net_total": float(net),
            "cashier_id": cashier_id,
        })
        return sale_id

    def generate_returns(self) -> None:
        sample_sales = random.sample(self.sale_records, min(len(self.sale_records) // 80, 400))
        reasons = [
            "Customer returned unused strips",
            "Wrong medicine given",
            "Expired medicine sold by mistake",
            "Doctor changed prescription",
            "Damaged packaging",
        ]
        for sale in sample_sales:
            if sale["payment_method"] not in ("cash", "card"):
                continue
            sale_id = sale["sale_id"]
            items = self.conn.execute(
                "SELECT medicine_id, batch_no, quantity, amount FROM sale_items WHERE sale_id=?",
                (sale_id,),
            ).fetchall()
            if not items:
                continue
            med_id, batch, qty, amount = random.choice(items)
            return_qty = max(1, qty // random.randint(1, 2))
            refund = money(float(amount) * return_qty / qty)
            return_date = (sale["sale_date"] + timedelta(days=random.randint(0, 7))).date()

            cur = self.conn.execute(
                """
                INSERT INTO returns (sale_id, return_date, reason, refund_amount, refund_method, processed_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sale_id, return_date.isoformat(), random.choice(reasons), float(refund),
                    random.choice(["cash", "credit"]), random.choice(self.cashier_ids),
                ),
            )
            return_id = cur.lastrowid
            self.conn.execute(
                "INSERT INTO return_items (return_id, medicine_id, batch_no, quantity, amount) VALUES (?,?,?,?,?)",
                (return_id, med_id, batch, return_qty, float(refund)),
            )
            self.conn.execute(
                "UPDATE stock SET quantity_strips = quantity_strips + ? WHERE medicine_id=? AND batch_no=?",
                (return_qty, med_id, batch),
            )
            self.add_ledger(
                med_id, batch, "return", return_id, return_qty,
                datetime.combine(return_date, datetime.min.time().replace(hour=15)),
            )

    def generate_supplier_payments(self) -> None:
        for record in self.purchase_records:
            age_days = (self.end_date - record["purchase_date"]).days
            pay_prob = 0.92 if age_days > 45 else 0.75 if age_days > 20 else 0.35
            if random.random() > pay_prob:
                continue

            pay_date = record["purchase_date"] + timedelta(days=random.randint(5, min(age_days, 60) or 5))
            if pay_date > self.end_date:
                pay_date = self.end_date - timedelta(days=random.randint(0, 5))

            amount = record["net_amount"]
            partial = random.random() < 0.08 and age_days < 30
            if partial:
                amount = round(amount * random.uniform(0.4, 0.7), 2)
                status = "partial"
            else:
                status = "paid"

            self.conn.execute(
                """
                INSERT INTO supplier_payments
                (supplier_id, purchase_id, payment_date, amount, payment_method, reference_no, paid_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["supplier_id"] if "supplier_id" in record else self.conn.execute(
                        "SELECT supplier_id FROM purchases WHERE purchase_id=?", (record["purchase_id"],)
                    ).fetchone()[0],
                    record["purchase_id"],
                    pay_date.isoformat(),
                    amount,
                    random.choice(["cash", "cheque", "bank_transfer"]),
                    f"CHQ-{random.randint(10000, 99999)}",
                    "Ahmed Hassan",
                ),
            )
            self.conn.execute(
                "UPDATE purchases SET payment_status=? WHERE purchase_id=?",
                (status, record["purchase_id"]),
            )
            record["payment_status"] = status

    def generate_cash_registers(self) -> None:
        sales_by_day_shift: dict[tuple[date, str, int], list] = defaultdict(list)
        returns_by_day: dict[date, float] = defaultdict(float)

        for sale in self.sale_records:
            d = sale["sale_date"].date()
            hour = sale["sale_date"].hour
            shift = "morning" if hour < 14 else "evening" if hour < 20 else "night"
            sales_by_day_shift[(d, shift, sale["cashier_id"])].append(sale)

        return_rows = self.conn.execute(
            "SELECT return_date, refund_amount, refund_method FROM returns"
        ).fetchall()
        for rdate, amt, method in return_rows:
            if method == "cash":
                returns_by_day[date.fromisoformat(rdate)] += amt

        d = self.start_date
        opening = 15000.0
        while d <= self.end_date:
            for shift in SHIFTS:
                for cashier_id in self.cashier_ids:
                    key = (d, shift, cashier_id)
                    shift_sales = sales_by_day_shift.get(key, [])
                    if not shift_sales and random.random() < 0.3:
                        continue

                    cash_total = sum(s["net_total"] for s in shift_sales if s["payment_method"] == "cash")
                    card_total = sum(s["net_total"] for s in shift_sales if s["payment_method"] == "card")
                    jazz_total = sum(s["net_total"] for s in shift_sales if s["payment_method"] == "jazzcash")
                    easypaisa_total = sum(s["net_total"] for s in shift_sales if s["payment_method"] == "easypaisa")
                    udhaar_total = sum(s["net_total"] for s in shift_sales if s["payment_method"] == "udhaar")

                    day_returns = returns_by_day.get(d, 0) / 3  # split across shifts
                    expenses = random.choice([0, 0, 200, 500, 800, 1200, 2500])
                    system_cash = opening + cash_total - day_returns - expenses
                    # Small natural variance
                    closing = system_cash + random.uniform(-150, 150)
                    difference = round(closing - system_cash, 2)

                    cur = self.conn.execute(
                        """
                        INSERT INTO cash_register
                        (shift_date, shift, cashier_id, opening_cash, total_sales_cash, total_sales_card,
                         total_sales_jazz, total_sales_easypaisa, total_sales_udhaar, total_returns_cash,
                         expenses_paid, closing_cash, system_cash, difference, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            d.isoformat(), shift, cashier_id, round(opening, 2),
                            round(cash_total, 2), round(card_total, 2), round(jazz_total, 2),
                            round(easypaisa_total, 2), round(udhaar_total, 2), round(day_returns, 2),
                            round(expenses, 2), round(closing, 2), round(system_cash, 2), difference,
                            None,
                        ),
                    )
                    register_id = cur.lastrowid
                    if expenses > 0:
                        self.conn.execute(
                            """
                            INSERT INTO expenses (expense_date, category, description, amount, paid_by, register_id)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                d.isoformat(), random.choice(EXPENSE_CATEGORIES),
                                random.choice(["Daily petty cash", "Shop expense", "Utility bill part payment"]),
                                expenses, "Usman Ali", register_id,
                            ),
                        )
                    opening = closing
            d += timedelta(days=1)

    def inject_discrepancies(self) -> None:
        """Plant realistic reconciliation problems for RAG to discover."""
        self.log("Injecting deliberate discrepancies for RAG testing...")

        # 1. Cash shorts on recent shifts
        recent_registers = self.conn.execute(
            """
            SELECT register_id, shift_date, shift, difference, system_cash, closing_cash
            FROM cash_register ORDER BY shift_date DESC LIMIT 60
            """
        ).fetchall()
        for i, row in enumerate(recent_registers[:18]):
            rid, sdate, shift, _, system_cash, _ = row
            short_amount = random.choice([1200, 2100, 3200, 4500, 5800, 7500, 9200])
            new_closing = round(system_cash - short_amount, 2)
            new_diff = round(new_closing - system_cash, 2)
            self.conn.execute(
                "UPDATE cash_register SET closing_cash=?, difference=?, notes=? WHERE register_id=?",
                (new_closing, new_diff, "Cash count mismatch - under investigation", rid),
            )
            self.flags.append({
                "flag_type": "cash_short",
                "severity": "high" if short_amount > 5000 else "medium",
                "entity_table": "cash_register",
                "entity_id": rid,
                "description": f"Cash register short on {sdate} {shift} shift",
                "expected_value": str(round(system_cash, 2)),
                "actual_value": str(new_closing),
                "flag_date": sdate,
                "hidden_answer": f"Closing cash is PKR {short_amount:,.0f} less than system expected. Check cash sales vs returns for that shift.",
            })

        # 2. Stock quantity doesn't match ledger
        stock_rows = self.conn.execute(
            "SELECT stock_id, medicine_id, batch_no, quantity_strips FROM stock ORDER BY RANDOM() LIMIT 35"
        ).fetchall()
        for stock_id, med_id, batch, qty in stock_rows:
            ledger_bal = self.ledger_balance.get((med_id, batch), qty)
            # Make stock table wrong
            wrong_qty = max(0, ledger_bal + random.choice([-12, -8, -5, 7, 10, 15, 20]))
            med_name = self.conn.execute("SELECT name FROM medicines WHERE medicine_id=?", (med_id,)).fetchone()[0]
            self.conn.execute("UPDATE stock SET quantity_strips=? WHERE stock_id=?", (wrong_qty, stock_id))
            self.flags.append({
                "flag_type": "stock_mismatch",
                "severity": "medium",
                "entity_table": "stock",
                "entity_id": stock_id,
                "description": f"Stock count mismatch for {med_name} batch {batch}",
                "expected_value": str(ledger_bal),
                "actual_value": str(wrong_qty),
                "flag_date": self.end_date.isoformat(),
                "hidden_answer": f"Ledger shows {ledger_bal} strips but stock table shows {wrong_qty}. Difference of {wrong_qty - ledger_bal} strips unaccounted.",
            })

        # 3. Unpaid supplier invoices > 30 days
        unpaid = self.conn.execute(
            """
            SELECT purchase_id, supplier_id, invoice_no, purchase_date, net_amount
            FROM purchases WHERE payment_status != 'paid'
            ORDER BY purchase_date ASC LIMIT 25
            """
        ).fetchall()
        for pid, sid, inv, pdate, net in unpaid[:12]:
            old_date = date.fromisoformat(pdate) - timedelta(days=random.randint(35, 90))
            self.conn.execute("UPDATE purchases SET purchase_date=?, payment_status='unpaid' WHERE purchase_id=?", (old_date.isoformat(), pid))
            supplier = self.conn.execute("SELECT company_name FROM suppliers WHERE supplier_id=?", (sid,)).fetchone()[0]
            days_overdue = (self.end_date - old_date).days
            self.flags.append({
                "flag_type": "unpaid_supplier_invoice",
                "severity": "high" if days_overdue > 60 else "medium",
                "entity_table": "purchases",
                "entity_id": pid,
                "description": f"Unpaid supplier invoice {inv} from {supplier}",
                "expected_value": "paid",
                "actual_value": f"unpaid PKR {net:,.0f}",
                "flag_date": self.end_date.isoformat(),
                "hidden_answer": f"Invoice {inv} dated {old_date} from {supplier} for PKR {net:,.0f} is unpaid for {days_overdue} days.",
            })

        # 4. Duplicate supplier payment
        dup_target = self.conn.execute(
            "SELECT purchase_id, supplier_id, net_amount FROM purchases WHERE payment_status='paid' LIMIT 1"
        ).fetchone()
        if dup_target:
            pid, sid, net = dup_target
            pay_row = self.conn.execute(
                "SELECT payment_date, amount FROM supplier_payments WHERE purchase_id=? LIMIT 1", (pid,)
            ).fetchone()
            if pay_row:
                self.conn.execute(
                    """
                    INSERT INTO supplier_payments
                    (supplier_id, purchase_id, payment_date, amount, payment_method, reference_no, paid_by, notes)
                    VALUES (?, ?, ?, ?, 'bank_transfer', ?, 'Ahmed Hassan', 'DUPLICATE - data entry error')
                    """,
                    (sid, pid, pay_row[0], pay_row[1], f"DUP-{random.randint(10000,99999)}"),
                )
                supplier = self.conn.execute("SELECT company_name FROM suppliers WHERE supplier_id=?", (sid,)).fetchone()[0]
                self.flags.append({
                    "flag_type": "duplicate_supplier_payment",
                    "severity": "critical",
                    "entity_table": "purchases",
                    "entity_id": pid,
                    "description": f"Duplicate payment detected for purchase #{pid}",
                    "expected_value": f"single payment PKR {pay_row[1]:,.0f}",
                    "actual_value": f"double payment PKR {pay_row[1]*2:,.0f}",
                    "flag_date": pay_row[0],
                    "hidden_answer": f"Purchase #{pid} from {supplier} was paid twice (PKR {pay_row[1]:,.0f} each). Second payment reference marked DUPLICATE.",
                })

        # 5. Overdue credit customers
        credit_customers = self.conn.execute(
            "SELECT customer_id, name, current_balance, credit_limit FROM customers WHERE current_balance > 0 ORDER BY current_balance DESC LIMIT 15"
        ).fetchall()
        for cid, name, balance, limit in credit_customers[:8]:
            inflated = round(float(balance) * random.uniform(1.2, 1.8), 2)
            self.conn.execute("UPDATE customers SET current_balance=? WHERE customer_id=?", (inflated, cid))
            over_limit = inflated > float(limit) if limit else inflated > 10000
            self.flags.append({
                "flag_type": "credit_overdue",
                "severity": "high" if over_limit else "medium",
                "entity_table": "customers",
                "entity_id": cid,
                "description": f"Customer {name} has outstanding udhaar balance",
                "expected_value": f"under limit PKR {limit:,.0f}" if limit else "timely payment",
                "actual_value": f"balance PKR {inflated:,.0f}",
                "flag_date": self.end_date.isoformat(),
                "hidden_answer": f"{name} owes PKR {inflated:,.0f}" + (f" exceeding credit limit of PKR {limit:,.0f}" if over_limit else "") + ".",
            })

        # 6. Expired stock still on shelves
        expired_stock = self.conn.execute(
            """
            SELECT stock_id, medicine_id, batch_no, quantity_strips, expiry_date
            FROM stock WHERE expiry_date < ? AND quantity_strips > 0 LIMIT 20
            """,
            (self.end_date.isoformat(),),
        ).fetchall()
        for stock_id, med_id, batch, qty, exp in expired_stock:
            med_name = self.conn.execute("SELECT name FROM medicines WHERE medicine_id=?", (med_id,)).fetchone()[0]
            self.flags.append({
                "flag_type": "expired_stock",
                "severity": "critical",
                "entity_table": "stock",
                "entity_id": stock_id,
                "description": f"Expired stock still in inventory: {med_name}",
                "expected_value": "0 quantity after expiry",
                "actual_value": f"{qty} strips, expired {exp}",
                "flag_date": self.end_date.isoformat(),
                "hidden_answer": f"{med_name} batch {batch} expired on {exp} but {qty} strips still show in stock.",
            })

        # 7. Returns not reflected in cash register
        if recent_registers:
            rid, sdate, shift, _, system_cash, closing_cash = recent_registers[0]
            extra_cash = 3500
            self.conn.execute(
                "UPDATE cash_register SET closing_cash=?, difference=? WHERE register_id=?",
                (closing_cash + extra_cash, (closing_cash + extra_cash) - system_cash, rid),
            )
            self.flags.append({
                "flag_type": "return_not_in_register",
                "severity": "medium",
                "entity_table": "cash_register",
                "entity_id": rid,
                "description": f"Cash register on {sdate} {shift} does not account for returns",
                "expected_value": "returns deducted from cash",
                "actual_value": f"PKR {extra_cash} return missing from register",
                "flag_date": sdate,
                "hidden_answer": f"A cash return of PKR {extra_cash:,.0f} was processed but not deducted from register #{rid}.",
            })

        # 8. Missing FBR QR on some recent sales
        recent_sales = self.conn.execute(
            "SELECT sale_id, invoice_no, net_total, sale_date FROM sales ORDER BY sale_date DESC LIMIT 40"
        ).fetchall()
        for sale_id, inv, net, sdate in recent_sales[:10]:
            self.conn.execute("UPDATE sales SET fbr_qr_code=NULL WHERE sale_id=?", (sale_id,))
            self.flags.append({
                "flag_type": "missing_fbr_qr",
                "severity": "high",
                "entity_table": "sales",
                "entity_id": sale_id,
                "description": f"Sale invoice {inv} missing FBR QR code",
                "expected_value": "FBR QR present",
                "actual_value": "NULL",
                "flag_date": sdate[:10],
                "hidden_answer": f"Invoice {inv} for PKR {net:,.0f} on {sdate[:10]} has no FBR QR — FBR compliance risk.",
            })

        # 9. Purchase amount vs payment mismatch
        mismatch_purchase = self.conn.execute(
            "SELECT purchase_id, supplier_id, net_amount FROM purchases WHERE payment_status='paid' ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
        if mismatch_purchase:
            pid, sid, net = mismatch_purchase
            wrong_payment = round(float(net) * 1.15, 2)
            self.conn.execute(
                "UPDATE supplier_payments SET amount=? WHERE purchase_id=?", (wrong_payment, pid)
            )
            supplier = self.conn.execute("SELECT company_name FROM suppliers WHERE supplier_id=?", (sid,)).fetchone()[0]
            self.flags.append({
                "flag_type": "payment_amount_mismatch",
                "severity": "high",
                "entity_table": "purchases",
                "entity_id": pid,
                "description": f"Supplier payment does not match purchase invoice amount",
                "expected_value": f"PKR {net:,.2f}",
                "actual_value": f"PKR {wrong_payment:,.2f}",
                "flag_date": self.end_date.isoformat(),
                "hidden_answer": f"Paid {supplier} PKR {wrong_payment:,.2f} against purchase #{pid} but invoice net amount is PKR {net:,.2f}. Overpaid by PKR {wrong_payment - float(net):,.2f}.",
            })

        # 10. DRAP price violation — retail below purchase (loss) or way above MRP pattern
        price_violations = self.conn.execute(
            "SELECT medicine_id, name, purchase_price, retail_price FROM medicines ORDER BY RANDOM() LIMIT 8"
        ).fetchall()
        for med_id, name, purchase, retail in price_violations[:4]:
            violated_retail = round(float(purchase) * 1.65, 2)  # excessive margin
            self.conn.execute("UPDATE medicines SET retail_price=? WHERE medicine_id=?", (violated_retail, med_id))
            self.flags.append({
                "flag_type": "drap_price_violation",
                "severity": "medium",
                "entity_table": "medicines",
                "entity_id": med_id,
                "description": f"Possible DRAP price violation: {name}",
                "expected_value": f"~PKR {retail}",
                "actual_value": f"PKR {violated_retail}",
                "flag_date": self.end_date.isoformat(),
                "hidden_answer": f"{name} retail price set to PKR {violated_retail} which may exceed DRAP notified price (was PKR {retail}).",
            })

        # Persist flags
        for f in self.flags:
            self.conn.execute(
                """
                INSERT INTO reconciliation_flags
                (flag_type, severity, entity_table, entity_id, description,
                 expected_value, actual_value, flag_date, hidden_answer)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f["flag_type"], f["severity"], f["entity_table"], f["entity_id"],
                    f["description"], f["expected_value"], f["actual_value"],
                    f["flag_date"], f["hidden_answer"],
                ),
            )

    def run(self) -> dict:
        self.log(f"Generating pharmacy data: {PHARMACY_NAME}, {PHARMACY_CITY}")
        self.log(f"Date range: {self.start_date} to {self.end_date} ({self.config.months} months)")
        self.insert_employees()
        self.insert_medicines()
        self.log(f"  Medicines: {len(self.medicine_ids)}")
        self.insert_suppliers()
        self.insert_customers()
        self.generate_initial_stock_and_purchases()
        self.log(f"  Purchases: {len(self.purchase_records)}")
        self.generate_sales()
        self.log(f"  Sales: {len(self.sale_records)}")
        self.generate_returns()
        self.generate_supplier_payments()
        self.generate_cash_registers()
        self.inject_discrepancies()
        self.conn.commit()

        stats = {
            table: self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in [
                "medicines", "suppliers", "customers", "stock", "stock_ledger",
                "purchases", "purchase_items", "sales", "sale_items",
                "cash_register", "supplier_payments", "returns", "expenses",
                "reconciliation_flags",
            ]
        }
        return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Pakistan pharmacy sample database")
    parser.add_argument("--output", default="data/bismillah_pharmacy.db", help="SQLite output path")
    parser.add_argument("--months", type=int, default=None, help="Override months of data")
    parser.add_argument("--scale", choices=list(SCALES.keys()), default="large", help="Data volume preset")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    config = SCALES[args.scale]
    if args.months:
        config = ScaleConfig(
            months=args.months,
            medicines_extra=config.medicines_extra,
            customers=config.customers,
            daily_sales_min=config.daily_sales_min,
            daily_sales_max=config.daily_sales_max,
            purchases_per_week=config.purchases_per_week,
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    conn = sqlite3.connect(output)
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    gen = PharmacyGenerator(conn, config, seed=args.seed)
    stats = gen.run()
    conn.close()

    print("\n=== Generation complete ===")
    print(f"Database: {output.resolve()}")
    print(f"Scale: {args.scale} | Months: {config.months} | Seed: {args.seed}")
    print("\nTable row counts:")
    for table, count in stats.items():
        print(f"  {table:25} {count:>8,}")
    print(f"\n  Deliberate discrepancies planted: {stats['reconciliation_flags']}")
    print("\nGround-truth answers are in reconciliation_flags.hidden_answer (for your eval only).")
    print("Sample queries to test your RAG:")
    print('  - "Aaj cash short kyun hai?"')
    print('  - "Kon se supplier ke unpaid invoices 30 din se zyada purane hain?"')
    print('  - "Panadol ka stock ledger se match kyun nahi kar raha?"')
    print('  - "Duplicate supplier payment dikhao"')


if __name__ == "__main__":
    main()
