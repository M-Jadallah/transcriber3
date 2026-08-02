import { useEffect, useRef, useState } from 'react';
import { get } from '../api';

/**
 * Reusable data-fetching hook with optional polling.
 *
 * @param path  API path (e.g. '/formatting/settings')
 * @param pollIntervalMs  When > 0, re-fetch at this interval (ms)
 */
export function useFetch<T>(
  path: string,
  pollIntervalMs: number = 0,
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const mountedRef = useRef(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchOnce() {
    try {
      const result = await get<T>(path);
      if (mountedRef.current) {
        setData(result);
        setError('');
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(
          err instanceof Error ? err.message : 'تعذر تحميل البيانات',
        );
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }

  function reload() {
    return fetchOnce();
  }

  useEffect(() => {
    mountedRef.current = true;
    fetchOnce();

    if (pollIntervalMs > 0) {
      intervalRef.current = setInterval(fetchOnce, pollIntervalMs);
    }

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [path, pollIntervalMs]);

  return { data, loading, error, reload };
}
