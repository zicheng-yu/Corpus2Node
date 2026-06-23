import { useState, useCallback } from "react";

export function useLocalStorage<T>(key: string, initialValue: T): [T, (v: T) => void] {
  const [stored, setStored] = useState<T>(() => {
    try {
      const item = localStorage.getItem(key);
      return item ? (JSON.parse(item) as T) : initialValue;
    } catch {
      return initialValue;
    }
  });

  const setValue = useCallback(
    (value: T) => {
      try {
        localStorage.setItem(key, JSON.stringify(value));
        setStored(value);
      } catch {
        // ignore write errors
      }
    },
    [key],
  );

  return [stored, setValue];
}
