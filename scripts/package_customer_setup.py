"""Build the customer-only setup archive without certificates or repository dependencies."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
FILES = ("setup.sh", "setup_account.py", "foundry-reader.json")
ARCHIVE = ROOT / "docs" / "downloads" / "customer-setup.zip"


def build_customer_setup(output: Path = ARCHIVE) -> Path:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in FILES:
            content = (ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n")
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, content)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(buffer.getvalue())
    return output


if __name__ == "__main__":
    print(build_customer_setup())
