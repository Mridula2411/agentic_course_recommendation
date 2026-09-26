import { useState } from 'react'
import Markdown from 'react-markdown'
import { SearchBar } from './Components/inputComponent'
import { CourseCard } from './Components/CourseCard'
import { SearchDetails } from './Components/SearchDetails'
import { FactCheck } from './Components/FactCheck'
import './App.css'

const API_URL = 'http://localhost:8000/chat'

const EXAMPLES = [
  'pass/fail courses about sustainability',
  'machine learning courses in P2',
  'project courses with no written exam',
]

export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [courses, setCourses] = useState([])
  const [total, setTotal] = useState(0)
  const [picks, setPicks] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const started = messages.length > 0

  async function send(text) {
    setMessages(prev => [...prev, { role: 'student', text }])
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      })
      const data = await response.json()
      setSessionId(data.session_id)
      if (data.error) {
        setError(data.error)
        return
      }
      setMessages(prev => [...prev, { role: 'advisor', text: data.message, search: data.search, verification: data.verification }])
      if (data.courses) {
        setCourses(data.courses)
        setTotal(data.search.total)
        setPicks([])
      }
      if (data.highlighted.length > 0) {
        setPicks(data.highlighted)
      }
    } catch {
      setError('Could not reach the server. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }

  function reset() {
    setSessionId(null)
    setMessages([])
    setCourses([])
    setTotal(0)
    setPicks([])
    setError(null)
  }

  const pickCodes = new Set(picks.map(p => p.course_code))
  const otherCourses = courses.filter(c => !pickCodes.has(c.course_code))

  return (
    <main>
      {!started && (
        <div className="hero">
          <h1 className="heroTitle newsreader-h1">KTH Course Search</h1>
          <h2 className="newsreader-h2 heroH2">Find courses using <span className="bold">natural language</span></h2>
        </div>
      )}

      {started && (
        <div className="chatLog montserrat-p">
          {messages.map((message, i) => (
            <div key={i} className={`chatMessage ${message.role}`}>
              {message.role === 'advisor' ? <Markdown>{message.text}</Markdown> : <p>{message.text}</p>}
              {message.search && <SearchDetails search={message.search} />}
              {message.verification && <FactCheck verification={message.verification} />}
            </div>
          ))}
          {loading && <div className="chatMessage advisor thinking">Thinking...</div>}
        </div>
      )}

      <SearchBar
        onSearch={send}
        disabled={loading}
        placeholder={started ? 'Ask a follow-up, e.g. "which of these is easiest?"' : undefined}
      />

      {!started && (
        <div className="examples montserrat-p">
          {EXAMPLES.map(example => (
            <button key={example} className="exampleChip" onClick={() => send(example)}>{example}</button>
          ))}
        </div>
      )}

      {started && <button className="newChatButton montserrat-p" onClick={reset}>New conversation</button>}
      {error && <p className="errorText montserrat-p">{error}</p>}

      {picks.length > 0 && (
        <section>
          <h3 className="sectionHeading montserrat-p">Advisor's picks</h3>
          <div className="courseCardParent">
            {picks.map(course => <CourseCard key={course.course_code} course={course} reason={course.reason} />)}
          </div>
        </section>
      )}

      {courses.length > 0 && (
        <section>
          <h3 className="sectionHeading montserrat-p">
            {picks.length > 0
              ? `${otherCourses.length} more courses`
              : total > courses.length ? `Showing ${courses.length} of ${total} courses` : `${courses.length} courses`}
          </h3>
          <div className="courseCardParent">
            {otherCourses.map(course => <CourseCard key={course.course_code} course={course} />)}
          </div>
        </section>
      )}
    </main>
  )
}
