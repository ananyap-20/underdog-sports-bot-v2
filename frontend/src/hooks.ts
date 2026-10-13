import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api";

export function useApi<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true); setError(null);
    api<T>(path).then((d) => live && setData(d)).catch((e: ApiError) => live && setError(e)).finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [path, nonce]);
  const retry = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, retry };
}
