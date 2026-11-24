// Long lists remain shareable and reloadable without being sent in the page URL.
export function readCatalogParams(location: Pick<Location, "search" | "hash"> = window.location) {
  const params = new URLSearchParams(location.search);
  const code = new URLSearchParams(location.hash.slice(1)).get("code");
  if (code !== null) params.set("code", code);
  return params;
}

export function catalogUrl(pathname: string, params: URLSearchParams) {
  const query = new URLSearchParams(params);
  const fragment = new URLSearchParams();
  if ((query.get("code") ?? "").length > 1500) {
    fragment.set("code", query.get("code")!);
    query.delete("code");
  }
  return `${pathname}${query.size ? `?${query}` : ""}${fragment.size ? `#${fragment}` : ""}`;
}

export function codeRequest(params: URLSearchParams) {
  const query = new URLSearchParams(params);
  const code = query.get("code") ?? "";
  if (code.length <= 1500) return { query, init: undefined };
  query.delete("code");
  return { query, init: { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) } };
}

export function codeList(value: string) {
  return value.trim().split(/[,\s]+/).filter(Boolean);
}
