(() => {
  const endpoint = window.NEXTPAY_QUEUE_URL || "/api/book";
  const listeners = new Set();
  let base=[], source="connecting", lastPayload="";
  const rows=()=>base;
  const idKey=r=>r.id;
  const statuses=new Set(["Eligible","Scheduled","Paused","Human review"]);
  const notify=()=>listeners.forEach(fn=>fn(base));
  async function importRows(input){
    const response=await fetch("/api/book",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});
    if(!response.ok)throw Error("Could not save the borrower list.");
    await refresh(false);
    return response.json();
  }
  async function refresh(schedule=true) {
    try {
      const response = await fetch(endpoint, {cache: "no-store", signal: AbortSignal.timeout(10000)});
      if (!response.ok) throw Error("Queue unavailable");
      const payload = await response.json();
      const incoming = Array.isArray(payload) ? payload : payload.borrowers;
      if (!Array.isArray(incoming) || !incoming.every(row => row && idKey(row) && statuses.has(row.status))) {
        throw Error("Invalid borrower data");
      }
      const serialized = JSON.stringify(incoming);
      if (source !== "live" || serialized !== lastPayload) {
        base = incoming;
        lastPayload = serialized;
        source = "live";
        notify();
      }
    } catch {
      if (source !== "offline") { source = "offline"; notify(); }
    } finally { if(schedule) window.setTimeout(refresh, 15000); }
  }
  window.QueueStore = {
    get source() { return source; },
    subscribe(fn) { listeners.add(fn); fn(rows()); return () => listeners.delete(fn); },
    refresh:()=>refresh(false), importRows
  };
  refresh();
})();