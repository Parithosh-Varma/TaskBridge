/** Simple mono table for dense reference content. */
export default function Table({ head, rows, className = '' }) {
  return (
    <div className={'table-wrap ' + className}>
      <table className="ref-table">
        <thead>
          <tr>{head.map(h => <th key={h}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j} className={j === 0 ? 'ref-key' : undefined}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
