export function exportToCSV(filename, headers, uplotData) {
  if (!uplotData || uplotData.length === 0) return;

  const rows = [];
  rows.push(headers.join(","));

  const length = uplotData[0].length;
  for (let i = 0; i < length; i++) {
    const row = uplotData.map(seriesData => {
      const v = seriesData[i];
      return v !== undefined && v !== null ? v : "";
    });
    rows.push(row.join(","));
  }

  const csvContent = "data:text/csv;charset=utf-8," + rows.join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
