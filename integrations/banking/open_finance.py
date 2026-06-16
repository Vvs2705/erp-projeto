import json
import re
from datetime import date
from decimal import Decimal
from typing import List, Dict, Any

class OpenFinanceParser:
    """
    Parser for bank statement files in OFX and JSON formats.
    """
    @staticmethod
    def parse_json(content: str) -> List[Dict[str, Any]]:
        """
        Parses JSON bank statement files.
        Expects a list of transactions or an object containing a 'transactions' key.
        """
        data = json.loads(content)
        raw_items = data.get("transactions", data) if isinstance(data, dict) else data
        
        if not isinstance(raw_items, list):
            raise ValueError("Invalid JSON statement format. Expected a list of transactions.")
            
        transactions = []
        for item in raw_items:
            tx_id = str(item.get("id", item.get("transactionId", "")))
            # Handle ISO date format
            tx_date = date.fromisoformat(item["date"])
            amount = Decimal(str(item["amount"]))
            description = item.get("description", item.get("memo", ""))
            tx_type = item.get("type", "CREDIT" if amount >= 0 else "DEBIT").upper()
            
            transactions.append({
                "id": tx_id,
                "date": tx_date,
                "amount": amount,
                "description": description,
                "type": tx_type
            })
        return transactions

    @staticmethod
    def parse_ofx(content: str) -> List[Dict[str, Any]]:
        """
        Parses standard OFX (Open Financial Exchange) bank statement files using regex.
        """
        transactions = []
        # Find all transaction blocks
        tx_blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", content, re.DOTALL)
        for block in tx_blocks:
            tx_type_match = re.search(r"<TRNTYPE>(.*)", block)
            dt_posted_match = re.search(r"<DTPOSTED>(.*)", block)
            trn_amt_match = re.search(r"<TRNAMT>(.*)", block)
            fit_id_match = re.search(r"<FITID>(.*)", block)
            memo_match = re.search(r"<MEMO>(.*)", block)
            name_match = re.search(r"<NAME>(.*)", block)

            tx_type = tx_type_match.group(1).strip() if tx_type_match else "CREDIT"
            
            # DTPOSTED format: YYYYMMDD[HHMMSS]
            dt_str = dt_posted_match.group(1).strip()[:8] if dt_posted_match else ""
            if len(dt_str) >= 8:
                tx_date = date(int(dt_str[:4]), int(dt_str[4:6]), int(dt_str[6:8]))
            else:
                tx_date = date.today()
                
            amount_str = trn_amt_match.group(1).strip() if trn_amt_match else "0.00"
            amount = Decimal(amount_str)
            tx_id = fit_id_match.group(1).strip() if fit_id_match else ""
            
            description = memo_match.group(1).strip() if memo_match else ""
            if not description and name_match:
                description = name_match.group(1).strip()

            transactions.append({
                "id": tx_id,
                "date": tx_date,
                "amount": amount,
                "description": description,
                "type": tx_type
            })
        return transactions

    @classmethod
    def parse(cls, content: str, file_format: str) -> List[Dict[str, Any]]:
        """
        General parse entrypoint. Decides which parser to run based on the file format.
        """
        fmt = file_format.lower().strip()
        if fmt == "json":
            return cls.parse_json(content)
        elif fmt == "ofx":
            return cls.parse_ofx(content)
        else:
            raise ValueError(f"Unsupported bank statement format: {file_format}")
