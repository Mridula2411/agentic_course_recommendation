import '../css/searchdetails.css';

export function FactCheck({verification}) {
    if (verification.error) {
        return <p className="factCheck">Not fact-checked (the check failed)</p>;
    }
    if (!verification.revised) {
        return <p className="factCheck">Fact-checked</p>;
    }
    return (
        <details className="searchDetails factCheck">
            <summary>Revised after a fact-check</summary>
            <ul>
                {verification.problems.map((problem, i) => <li key={i}>{problem}</li>)}
            </ul>
        </details>
    );
}
