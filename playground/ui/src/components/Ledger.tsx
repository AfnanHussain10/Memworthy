// The append-only decision ledger, folded away: download it or peek at the raw JSONL.
export function Ledger({ jsonl }: { jsonl: string }) {
  function download() {
    const url = URL.createObjectURL(new Blob([jsonl], { type: "application/jsonl" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "memworthy.ledger.jsonl" });
    a.click();
    URL.revokeObjectURL(url);
  }
  const lines = jsonl.trim().split("\n").length - 1;
  return (
    <details className="ledger">
      <summary>
        Ledger <span className="muted">· every decision is also written to an append-only JSONL file ({lines} entries)</span>
      </summary>
      <div className="row"><button className="small" onClick={download}>Download memworthy.ledger.jsonl</button></div>
      <pre>{jsonl}</pre>
    </details>
  );
}
