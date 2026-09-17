from db.models import RecallUpc


def find_by_upc(session, upc: str | None) -> list[str]:
    """Returns recall_ids with an exact UPC match. Empty list if no UPC or no match."""
    if not upc:
        return []
    rows = session.query(RecallUpc.recall_id).filter_by(upc=upc).all()
    return [str(row[0]) for row in rows]