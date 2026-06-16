import uuid
from decimal import Decimal
from datetime import date
from typing import Dict, Any

class PixSlipGateway:
    """
    Simulated gateway for generating Pix and Boleto billing payloads.
    """
    @staticmethod
    def generate_pix(
        amount: Any,
        due_date: date,
        description: str,
        txid: str = None
    ) -> Dict[str, Any]:
        """
        Simulates Pix billing generation, returning QR Code URL and Pix Copy & Paste string.
        """
        if not txid:
            txid = uuid.uuid4().hex
            
        amount_dec = Decimal(str(amount))
        # Simulated Pix Copy & Paste payload
        br_code = f"00020101021226580014br.gov.bcb.pix2536pix.example.com/qr/v2/{txid}5204000053039865404{amount_dec:.2f}5802BR5915ERP SYSTEM LTDA6009SAO PAULO62070503***6304"
        
        return {
            "gateway": "pix_slip_gateway_mock",
            "txid": txid,
            "amount": amount_dec,
            "due_date": due_date.isoformat() if isinstance(due_date, date) else due_date,
            "pix_copy_paste": br_code,
            "pix_qr_code_url": f"https://api.example.com/v2/pix/qr/{txid}.png",
            "status": "active"
        }

    @staticmethod
    def generate_boleto(
        amount: Any,
        due_date: date,
        customer_name: str,
        customer_cnpj: str,
        our_number: str = None
    ) -> Dict[str, Any]:
        """
        Simulates Boleto billing generation, returning barcode, digitable line, and billing details.
        """
        if not our_number:
            our_number = f"3419{uuid.uuid4().int % 100000000000:011d}"
            
        amount_dec = Decimal(str(amount))
        # Simulated barcode based on date and amount
        date_factor = "9999" # simulated date factor
        barcode = f"34199{date_factor}{int(amount_dec * 100):010d}{our_number}"
        # Simulated digitable line
        digitable_line = f"34191.79001 01043.500574 91020.150008 7 {barcode[4:9]} {barcode[9:19]}"
        
        return {
            "gateway": "pix_slip_gateway_mock",
            "our_number": our_number,
            "amount": amount_dec,
            "due_date": due_date.isoformat() if isinstance(due_date, date) else due_date,
            "barcode": barcode,
            "digitable_line": digitable_line,
            "customer_name": customer_name,
            "customer_cnpj": customer_cnpj,
            "status": "active"
        }
