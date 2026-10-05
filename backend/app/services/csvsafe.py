def safe_cell(value) -> str:
    """Neutralise spreadsheet formula injection: a cell starting with
    = + - @ (or a tab/CR) would be executed as a formula when the CSV is
    opened in Excel/Sheets. Prefixing an apostrophe makes it plain text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
