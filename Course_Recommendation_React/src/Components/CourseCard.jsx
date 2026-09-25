import '../css/coursecard.css';
import globe from '../assets/globe.svg';
import university from '../assets/mdi_university-outline.svg';
import passrate from '../assets/passrate.svg';
import star from '../assets/star.svg';

export function CourseCard({course}) {
    console.log("Course", course);

    return (
        <div className="courseCard" key={course.course_code}>
        
            <div className="contentParent">

                <div className='courseCardHeader montserrat-p-header'>
                    <p>{course.course_code}</p>
                    <p>Interactive Media Technology</p>
                    <p>{course.credits} Credits</p>
                </div>

                <h3 className='courseTitle'>{course.course_name}</h3>
                <div className='iconGrandParent'>
                    <div className="iconParent">
                        <img src={star} alt="" width={20}/>
                        <p className='montserrat-p'>{course.rating}</p>
                    </div>
                    <div className="iconParent">
                        <img src={passrate} alt="" width={20} />
                        <p className='montserrat-p'>{course.pass_rate*100}%</p>
                    </div>
                    <div className="iconParent">
                        <img src={university} alt="" width={20}/>
                        <p className='montserrat-p'>{course.offered_period}</p>
                    </div>
                  
                   
                    
                </div>
                <p className='courseDescription'>{course.course_name=="Interactive Visualisation of Virtual Urban Environments and Computational Urban Design" ? null : course.short_description}</p>

                <div className='flexParent'>
                    <p className='monteserrat-p'>Examination: {course.examination}</p>
                    <a href={course.course_link} target="_blank" className='courseLink'>Link to course</a>
                </div>
                   
               
            </div>
        
            
        </div>
    )
}