from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Any, Union

class TaxEngine:
    @staticmethod
    def calculate_taxes(
        amount: Union[Decimal, float, str, int],
        issue_date: Union[date, datetime, str],
        is_service: bool = False,
        icms_rate: Union[Decimal, float, str] = "0.18",
        ipi_rate: Union[Decimal, float, str] = "0.05",
        pis_rate: Union[Decimal, float, str] = "0.0165",
        cofins_rate: Union[Decimal, float, str] = "0.076",
        iss_rate: Union[Decimal, float, str] = "0.05",
    ) -> Dict[str, Decimal]:
        """
        Computes standard Brazilian taxes and the CBS/IBS 2026 reform transition rates.
        
        Args:
            amount: The base value for tax calculation.
            issue_date: Date or datetime of emission.
            is_service: True if service (applies ISS/PIS/COFINS), False if product (applies ICMS/IPI/PIS/COFINS).
            icms_rate: ICMS tax rate (default: 18%)
            ipi_rate: IPI tax rate (default: 5%)
            pis_rate: PIS tax rate (default: 1.65%)
            cofins_rate: COFINS tax rate (default: 7.6%)
            iss_rate: ISS tax rate (default: 5%)
            
        Returns:
            Dict containing individual tax amounts and the total_taxes.
        """
        # Ensure base amount is Decimal
        amount_dec = Decimal(str(amount))
        
        # Parse issue_date into a date object
        if isinstance(issue_date, datetime):
            parsed_date = issue_date.date()
        elif isinstance(issue_date, str):
            # Try parsing date, then datetime
            try:
                parsed_date = date.fromisoformat(issue_date)
            except ValueError:
                parsed_date = datetime.fromisoformat(issue_date).date()
        else:
            parsed_date = issue_date

        # Initialize tax dictionary
        taxes = {
            "icms": Decimal("0.00"),
            "ipi": Decimal("0.00"),
            "pis": Decimal("0.00"),
            "cofins": Decimal("0.00"),
            "iss": Decimal("0.00"),
            "cbs": Decimal("0.00"),
            "ibs": Decimal("0.00"),
            "total_taxes": Decimal("0.00"),
        }

        # Traditional taxes
        if is_service:
            taxes["iss"] = (amount_dec * Decimal(str(iss_rate))).quantize(Decimal("0.01"))
            taxes["pis"] = (amount_dec * Decimal(str(pis_rate))).quantize(Decimal("0.01"))
            taxes["cofins"] = (amount_dec * Decimal(str(cofins_rate))).quantize(Decimal("0.01"))
        else:
            taxes["icms"] = (amount_dec * Decimal(str(icms_rate))).quantize(Decimal("0.01"))
            taxes["ipi"] = (amount_dec * Decimal(str(ipi_rate))).quantize(Decimal("0.01"))
            taxes["pis"] = (amount_dec * Decimal(str(pis_rate))).quantize(Decimal("0.01"))
            taxes["cofins"] = (amount_dec * Decimal(str(cofins_rate))).quantize(Decimal("0.01"))

        # 2026 Tax Reform transition highlight
        if parsed_date >= date(2026, 1, 1):
            taxes["cbs"] = (amount_dec * Decimal("0.009")).quantize(Decimal("0.01"))
            taxes["ibs"] = (amount_dec * Decimal("0.001")).quantize(Decimal("0.01"))

        # Calculate sum of all taxes
        taxes["total_taxes"] = sum(v for k, v in taxes.items() if k != "total_taxes")
        return taxes
