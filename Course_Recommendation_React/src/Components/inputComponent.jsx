import { useState } from "react";

import '../css/inputcomponent.css';


export function SearchBar({onSearch, disabled, placeholder}) {
    const [searchPhrase, setSearchPhrase] = useState('');

    function submit() {
        const text = searchPhrase.trim();
        if (text !== '' && !disabled) {
            onSearch(text);
            setSearchPhrase('');
        }
    }

    return (
        <div className="searchBarParent">
            <input
                type="search"
                id="searchBar"
                value={searchPhrase}
                onChange={e => setSearchPhrase(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && submit()}
                className="searchbar montserrat-p"
                placeholder={placeholder || "Ex. I would like to take a course in computer science, max 9 credits"}
            />
            <button onClick={submit} className="button" disabled={disabled}>Find courses</button>
        </div>
    );
}
