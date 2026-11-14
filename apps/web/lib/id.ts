// A random identifier for one user action, sent as the Idempotency-Key of a request.
//
// crypto.randomUUID() exists only on secure pages: https, or http://localhost. Opened over
// plain http under any other name (a phone pointed at a development machine on the office
// network, say) it is missing, and calling it would stop the action with a raw error.
// crypto.getRandomValues() is available everywhere, so the same kind of identifier
// (a version 4 UUID) is built from it instead.
export function newRequestId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const hex = Array.from(bytes, (byte, index) => {
    // Two fields mark the identifier as a random (version 4) UUID.
    const value = index === 6 ? (byte & 0x0f) | 0x40 : index === 8 ? (byte & 0x3f) | 0x80 : byte;
    return value.toString(16).padStart(2, "0");
  }).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
