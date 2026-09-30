"""Generate isolated test CA/server certificates under ignored auth-state/."""
import ipaddress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

destination = Path(__file__).resolve().parents[2] / "auth-state" / "https-test"
destination.mkdir(parents=True, exist_ok=True)
now = datetime.now(UTC)
ca_path = destination / "ca.pem"
if not ca_path.exists() or x509.load_pem_x509_certificate(ca_path.read_bytes()).not_valid_after_utc <= now + timedelta(days=1):
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WSO isolated test CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=7))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    certificate = (x509.CertificateBuilder()
                   .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
                   .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=7))
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                  x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                   .sign(ca_key, hashes.SHA256()))
    (destination / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (destination / "server.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    (destination / "server-key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
print(destination)
