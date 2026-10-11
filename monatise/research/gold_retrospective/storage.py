"""Selective admitted reads on the existing isolated research document table."""
from monatise.application.persistence import DurableRecord, PostgresDocumentStore
from monatise.research.broker_xauusd.archive import TABLE
from monatise.research.broker_xauusd.models import instant


class AdmittedResearchStore(PostgresDocumentStore):
    def __init__(self, connection):
        super().__init__(connection,table=TABLE)

    async def list_admitted(self, namespace, cutoff):
        # Canonical receipts use UTC ISO strings. Existing namespace/key primary
        # key serves this bounded workload; no new migration/index is justified.
        rows = await self._fetch(
            f"SELECT b.document_key AS batch_key,b.value AS batch_value,b.version AS batch_version,"
            f"a.document_key AS admission_key,a.value AS admission_value,a.version AS admission_version "
            f"FROM {TABLE} a JOIN {TABLE} b ON b.namespace=a.namespace "
            f"AND b.document_key='batch:' || (a.value->>'batch_id') "
            f"WHERE a.namespace=$1 AND left(a.document_key,10)='admission:' "
            f"AND (a.value->>'ingested_and_available_at')::timestamptz <= $2::timestamptz ORDER BY a.document_key",
            namespace,instant(cutoff).isoformat())
        documents = []
        for row in rows:
            for prefix in ("batch","admission"):
                documents.append(DurableRecord(namespace,row[prefix+"_key"],row[prefix+"_value"],row[prefix+"_version"]))
        return tuple(documents)
