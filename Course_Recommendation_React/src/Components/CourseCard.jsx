import '../css/coursecard.css';
import university from '../assets/mdi_university-outline.svg';
import passrate from '../assets/passrate.svg';
import star from '../assets/star.svg';

function shorten(text, length) {
    if (!text || text.length <= length) return text;
    return text.slice(0, text.lastIndexOf(' ', length)) + '...';
}

export function CourseCard({course, reason}) {
    const demo = course.ratings_source === 'synthetic';
    const exam = course.has_written_exam ? 'Written exam' : 'No written exam';

    return (
        <div className={reason ? 'courseCard picked' : 'courseCard'}>
            <div className="contentParent">
                <div className="courseCardHeader montserrat-p-header">
                    <p>{course.course_code}</p>
                    <p>{course.credits} credits</p>
                </div>

                <h3 className="courseTitle">{course.course_name}</h3>

                <div className="iconGrandParent">
                    {course.rating != null && (
                        <div className="iconParent" title="Student rating (1-5)">
                            <img src={star} alt="" width={20}/>
                            <p className="montserrat-p">{course.rating}</p>
                        </div>
                    )}
                    {course.pass_rate != null && (
                        <div className="iconParent" title="Pass rate">
                            <img src={passrate} alt="" width={20}/>
                            <p className="montserrat-p">{Math.round(course.pass_rate * 100)}%</p>
                        </div>
                    )}
                    <div className="iconParent" title="Study periods">
                        <img src={university} alt="" width={20}/>
                        <p className="montserrat-p">{course.periods || 'Not scheduled'}</p>
                    </div>
                    {demo && <span className="demoBadge" title="Rating, pass rate and reviews are generated placeholders">demo data</span>}
                </div>

                {reason && <p className="courseReason">{reason}</p>}
                <p className="courseDescription">{shorten(course.description, 200)}</p>

                <div className="flexParent">
                    <p className="montserrat-p examText">{exam}, graded {course.grading_scale}</p>
                    <a href={course.url} target="_blank" rel="noreferrer" className="courseLink">Course page</a>
                </div>
            </div>
        </div>
    )
}
