import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "/api",
  timeout: 15000,
});

export function errorMessage(error) {
  const detail = error?.response?.data?.detail;
  return Array.isArray(detail)
    ? detail.map((item) => item.msg).join(", ")
    : detail || error?.message || "Something went wrong. Please try again.";
}

export async function exportCollections() {
  const response = await api.get("/reports/collections.csv", { responseType: "blob" });
  const url = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = "collectflow-collections.csv";
  link.click();
  URL.revokeObjectURL(url);
}

export default api;
