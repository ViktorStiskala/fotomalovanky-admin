import { API_URL } from "@/lib/config";

export const customFetch = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(`${API_URL}${url}`, {
    ...options,
    headers: {
      ...options.headers,
    },
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const errorMessage = data?.detail || "Request failed";
    throw new Error(errorMessage);
  }

  // Orval expects { data, status, headers } shape
  return {
    data,
    status: response.status,
    headers: response.headers,
  } as T;
};
