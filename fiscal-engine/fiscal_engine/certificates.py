import base64
import hashlib
from typing import Optional

class MockCertificateSigner:
    """
    A class that simulates signing XML invoices using a mock A1 digital certificate (.pfx).
    """
    def __init__(self, pfx_data: bytes, password: str):
        self.pfx_data = pfx_data
        self.password = password

    def sign_xml(self, xml_content: str, tag_to_sign: str = "infNFe") -> str:
        """
        Signs the XML content by computing a SHA256 digest of the specified tag,
        generating a mock signature, and embedding a standard-compliant <Signature> element.
        """
        content_to_sign = xml_content
        if f"<{tag_to_sign}" in xml_content:
            try:
                start = xml_content.find(f"<{tag_to_sign}")
                end = xml_content.find(f"</{tag_to_sign}>")
                if start != -1 and end != -1:
                    content_to_sign = xml_content[start:end + len(f"</{tag_to_sign}>")]
            except Exception:
                pass
        
        # Calculate SHA256 digest
        digest = hashlib.sha256(content_to_sign.encode("utf-8")).hexdigest()
        
        # Encode certificate information into the mock signature value
        signature_value_raw = f"MOCK_SIGNATURE[{digest}]:cert_len={len(self.pfx_data)}:pass={self.password}"
        signature_value = base64.b64encode(signature_value_raw.encode("utf-8")).decode("utf-8")
        
        signature_xml = f"""
  <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">
      <SignedInfo>
          <SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha256"/>
          <Reference URI="">
              <DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
              <DigestValue>{digest}</DigestValue>
          </Reference>
      </SignedInfo>
      <SignatureValue>{signature_value}</SignatureValue>
      <KeyInfo>
          <X509Data>
              <X509Certificate>MOCK_A1_CERTIFICATE_PUBLIC_KEY_DATA</X509Certificate>
          </X509Data>
      </KeyInfo>
  </Signature>"""
        
        # Insert signature right before the root's closing tag
        last_closing_index = xml_content.rfind("</")
        if last_closing_index != -1:
            signed_xml = xml_content[:last_closing_index] + signature_xml + "\n" + xml_content[last_closing_index:]
            return signed_xml
        
        return xml_content + signature_xml
