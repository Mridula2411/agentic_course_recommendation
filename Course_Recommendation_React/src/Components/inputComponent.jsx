import { useState } from "react";

import '../css/inputcomponent.css';


export function SearchBar({onSearch}) {
    const [searchPhrase, setSearchPhrase] = useState('');

    function handleClick() {
        {if (searchPhrase !== ''){ onSearch(searchPhrase);console.log("Searching for:", searchPhrase)}}
       
    }

    function handleEnter(e) {
        {if (e.key === 'Enter') {
            {if (searchPhrase !== ''){ onSearch(searchPhrase);console.log("Searching for:", searchPhrase)}}
        }}
    }

    return (
         <div>
             <input type="search" id="searchBar" onChange={e => setSearchPhrase(e.target.value) } onKeyDown={e => handleEnter(e)} className="searchbar montserrat-p" placeholder="Ex. I would like to take a course in computer science, max 9 credits"/>
             <button onClick={() => handleClick()} className="button">Find courses</button>
         </div>
        
    );
}


// 
