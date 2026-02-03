export default function StatCard({ label, value, accent }) {
  return (
    <div className="stat-card" style={{ borderColor: accent }}>
      <p className="stat-label">{label}</p>
      <p className="stat-value" style={{ color: accent }}>{value}</p>
    </div>
  );
}
