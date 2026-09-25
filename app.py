import json
import os
from datetime import datetime
from data_setup import setup_database
from nlp_engine import extract_intent
from query_engine import build_safe_query, execute_query



# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")


def main():

    setup_database()
    
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    print("\n AI Course Recommendation System")
    print("Type 'exit' to quit\n")

    while True:

        user_input = input("Enter your requirement: ")

        if user_input.lower() == "exit":
            break

        #Extract structured intent
        intent = extract_intent(user_input)
        print("\n[DEBUG] Extracted Intent:")
        print(intent)

        if not intent:
            print("Could not understand request.\n")
            continue

        #Build safe SQL
        query, params = build_safe_query(intent)

        print("\n[DEBUG] Generated Safe SQL:")
        print(query)
        print("Params:", params)

        #Execute
        results = execute_query(query, params)

        # Ensure course_link and short_description are present in each course
        for course in results:
            course["course_link"] = course.get("course_link", "")
            course["short_description"] = course.get("short_description", "")

        filepath = os.path.join(RESULTS_DIR, "course_results.json")
        output_data = {
            "query": user_input,
            "intent": intent,
            "sql": query,
            "params": params,
            "results": results,
            "timestamp": datetime.now().isoformat()
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=4, ensure_ascii=False)

        print(f"\n Found {len(results)} course(s)")
        print(f" Results saved to: course_results.json")
        print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    main()