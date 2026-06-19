import csv
import io
import re
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance import BankTransaction, Partner


class MigrationService:
    @staticmethod
    async def import_partners_csv(
        db: AsyncSession, tenant_id: uuid.UUID, csv_content: str
    ) -> list[Partner]:
        """
        Parses partners data from a CSV string and persists them in the database.
        Detects comma or semicolon as a delimiter.
        Expected headers: name, cnpj, type
        CNPJ will be stripped of non-alphanumeric characters.
        If a partner with the same CNPJ and tenant_id already exists, updates
        the name and type.
        """
        if not csv_content.strip():
            return []

        # Detect delimiter: simple check of first line
        first_line = csv_content.strip().split("\n")[0]
        delimiter = ";" if ";" in first_line else ","

        f = io.StringIO(csv_content.strip())
        reader = csv.DictReader(f, delimiter=delimiter)

        # Normalize headers (lowercase and stripped)
        if reader.fieldnames:
            reader.fieldnames = [field.strip().lower() for field in reader.fieldnames]
        else:
            raise ValueError("CSV headers are missing.")

        imported_partners: list[Partner] = []

        for row in reader:
            name = row.get("name", "")
            name = name.strip() if name is not None else ""

            cnpj_raw = row.get("cnpj", "")
            cnpj_raw = cnpj_raw.strip() if cnpj_raw is not None else ""

            ptype = row.get("type", "")
            ptype = ptype.strip().lower() if ptype is not None else ""

            if not name or not cnpj_raw or not ptype:
                continue

            # Strip CNPJ from formatting: remove '.', '-', '/'
            cnpj = re.sub(r"[^A-Za-z0-9]", "", cnpj_raw)

            # Validate CNPJ format (Brazilian Alphanumeric CNPJ is 14 characters)
            if len(cnpj) != 14:
                raise ValueError(
                    f"CNPJ must be exactly 14 characters, "
                    f"got '{cnpj_raw}' (parsed as '{cnpj}')"
                )

            if ptype not in ["customer", "supplier", "both"]:
                raise ValueError(
                    f"Invalid partner type '{ptype}'. "
                    "Must be 'customer', 'supplier', or 'both'."
                )

            # Check if partner already exists for this tenant
            stmt = select(Partner).where(
                Partner.tenant_id == tenant_id, Partner.cnpj == cnpj
            )
            res = await db.execute(stmt)
            existing_partner = res.scalar_one_or_none()

            if existing_partner:
                existing_partner.name = name
                existing_partner.type = ptype
                existing_partner.updated_at = datetime.utcnow()
                imported_partners.append(existing_partner)
            else:
                new_partner = Partner(
                    tenant_id=tenant_id, name=name, cnpj=cnpj, type=ptype
                )
                db.add(new_partner)
                imported_partners.append(new_partner)

        await db.flush()
        return imported_partners

    @staticmethod
    async def import_bank_statement_ofx(
        db: AsyncSession, tenant_id: uuid.UUID, ofx_content: str
    ) -> list[BankTransaction]:
        """
        Parses a simplified OFX bank statement file and stores the transaction records.
        Expected fields inside <STMTTRN>: <DTPOSTED>, <TRNAMT>, <FITID>,
        <MEMO> or <NAME>
        FITID is used to prevent duplicate imports per tenant.
        """
        if not ofx_content.strip():
            return []

        imported_transactions: list[BankTransaction] = []

        # Split content by <STMTTRN>
        parts = ofx_content.split("<STMTTRN>")
        for part in parts[1:]:  # skip headers
            # Extract fields using regex
            dtposted_match = re.search(r"<DTPOSTED>\s*([0-9]{8})", part, re.IGNORECASE)
            trnamt_match = re.search(r"<TRNAMT>\s*(-?[0-9.]+)", part, re.IGNORECASE)
            fitid_match = re.search(r"<FITID>\s*([^\s<]+)", part, re.IGNORECASE)

            # Description can be in <MEMO> or <NAME>
            memo_match = re.search(r"<MEMO>\s*([^<\r\n]+)", part, re.IGNORECASE)
            name_match = re.search(r"<NAME>\s*([^<\r\n]+)", part, re.IGNORECASE)

            description = ""
            if name_match:
                description = name_match.group(1).strip()
            if memo_match:
                memo = memo_match.group(1).strip()
                description = f"{description} - {memo}" if description else memo

            if not description:
                description = "Bank Transaction"

            if not fitid_match or not trnamt_match or not dtposted_match:
                continue

            fitid = fitid_match.group(1).strip()
            amount_str = trnamt_match.group(1).strip()
            date_str = dtposted_match.group(1).strip()

            transaction_date = datetime.strptime(date_str, "%Y%m%d").date()
            amount = Decimal(amount_str)

            # Check if this FITID already exists for the tenant
            stmt = select(BankTransaction).where(
                BankTransaction.tenant_id == tenant_id, BankTransaction.fitid == fitid
            )
            res = await db.execute(stmt)
            existing_tx = res.scalar_one_or_none()

            if existing_tx:
                continue

            new_tx = BankTransaction(
                tenant_id=tenant_id,
                fitid=fitid,
                transaction_date=transaction_date,
                amount=amount,
                description=description,
                reconciled=False,
            )
            db.add(new_tx)
            imported_transactions.append(new_tx)

        await db.flush()
        return imported_transactions
