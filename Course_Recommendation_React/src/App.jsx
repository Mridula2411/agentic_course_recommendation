import { useState } from 'react'
import {SearchBar} from './Components/inputComponent'
import './App.css';
// import myCourses from '../../results/course_results.json';
import { CourseCard } from './Components/CourseCard';


export default function App() {
  const [searchResult, setSearchResult] = useState('');
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [isSearched, setisSearched] = useState(false);

  async function handleSearch(query) {
    setSearchResult(query);
    setLoading(true);
    setError(null);
    setisSearched(true);
    try {
      const response = await fetch('http://localhost:8000/recommend', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ user_input: query }),
      });
      const data = await response.json();
      if (data.results) {
        setCourses(data.results);
      } else {
        setCourses([]);
        setError(data.error || 'No results found.');
      }
    } catch (err) {
      setError('Failed to fetch results.');
      setCourses([]);
    } finally {
      setLoading(false);
    }
  }

  return (
     <main>
        <div>
          {!isSearched ? <h1 className="heroTitle newsreader-h1">KTH Course Search</h1> : null}
          {!isSearched ? <h2 className="newsreader-h2 heroH2">Find courses using <span className='bold'>natural language</span></h2> : null} 
          <SearchBar onSearch={handleSearch}/>
          {isSearched ? <p className='resultsP montserrat-p'>Showing {courses.length} results</p> : null}
          
        </div>
        
        {loading && <p>Loading...</p>}
        {error && <p style={{ color: 'red' }}>{error}</p>}
        <div className='courseCardParent'>
          {courses.map(course => (<CourseCard course={course}/>))}
        </div>
     </main>
      
  )
}

// Relevant courses <span className="bold">for you</span>, only <span className="bold">one search away</span>