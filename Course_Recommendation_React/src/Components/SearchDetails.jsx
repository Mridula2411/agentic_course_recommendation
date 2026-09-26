import '../css/searchdetails.css';

export function SearchDetails({search}) {
    return (
        <details className="searchDetails">
            <summary>How this was found</summary>
            <ol>
                {search.steps.map((step, i) => (
                    <li key={i}>
                        <span className="stepTool">{step.tool === 'submit_query' ? 'Final query' : 'Test query'}</span>
                        {step.error
                            ? <span className="stepError"> error: {step.error}</span>
                            : step.rows != null && <span> {step.rows} rows</span>}
                        <pre>{step.sql}</pre>
                    </li>
                ))}
            </ol>
        </details>
    )
}
