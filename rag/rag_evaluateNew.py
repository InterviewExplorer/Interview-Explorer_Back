import os
from datetime import datetime, timedelta
from elasticsearch import Elasticsearch
import json
from openai import OpenAI
from dotenv import load_dotenv
import time
import torch
from transformers import BertTokenizer, BertModel

# Load environment variables
load_dotenv()

# 설정
ELASTICSEARCH_HOST = os.getenv("elastic")
API_KEY = os.getenv("API_KEY")
GPT_MODEL = os.getenv("gpt")

if API_KEY is None:
    raise ValueError("API_KEY가 없습니다.")
if GPT_MODEL is None:
    raise ValueError("GPT_Model이 없습니다.")

client = OpenAI(api_key=API_KEY)

# Elasticsearch 클라이언트 설정
es = Elasticsearch([ELASTICSEARCH_HOST])

# BERT 모델 및 토크나이저 불러오기
tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
model = BertModel.from_pretrained('bert-base-uncased')

# 질문을 벡터로 변환하는 함수
def get_vector(text):
    inputs = tokenizer(text, return_tensors='pt')
    with torch.no_grad():
        outputs = model(**inputs)
    return outputs.last_hidden_state[0][0].numpy()

# 현재 날짜로 부터 30일 전 까지의 날짜 함수
def get_date_range(days: int):
    today = datetime.now()
    start_date = today - timedelta(days=days)
    return today.strftime("%Y-%m-%d"), start_date.strftime("%Y-%m-%d")

# Elasticsearch에서 벡터 기반 검색을 수행하는 함수
def searchDocs_evaluate(answers: str, index_name: str, type: str, explain=True, profile=True):
    today_str, thirty_days_ago_str = get_date_range(30)
    query_vector = get_vector(answers).tolist()
    must_queries = []

    if type == "behavioral":
        must_queries.append({
            "range": {
                "date_field": {
                    "gte": thirty_days_ago_str,
                    "lte": today_str
                }
            }
        })

    must_queries.append({
        "bool": {
            "should": [
                {
                    "match": {
                        "question": {
                            "query": answers,
                            "fuzziness": "AUTO"
                        }
                    }
                },
                {
                    "script_score": {
                        "query": {
                            "match_all": {}
                        },
                        "script": {
                            "source": "cosineSimilarity(params.query_vector, 'vector') + 1.0",
                            "params": {
                                "query_vector": query_vector
                            }
                        }
                    }
                }
            ]
        }
    })

    response = es.search(
        index=index_name,
        body={
            "query": {
                "bool": {
                    "must": must_queries
                }
            },
            "size": 50,
            "explain": explain,
            "profile": profile
        }
    )

    hits = response['hits']['hits']

    # print("\n유사성 판단 근거:")
    # for i, hit in enumerate(hits):
    #     print(f"\n문서 {i+1}:")
    #     print(f"질문: {hit['_source']['question']}")
    #     print(f"유사도 점수: {hit['_score']:.2f}")
    
    #     if '_explanation' in hit:
    #         explanation = hit['_explanation']
    #         print("유사성 판단 이유:")
    #         print_human_readable_explanation(explanation)

    return [hit['_source']['question'] for hit in hits]

def print_human_readable_explanation(explanation):
    if 'description' in explanation:
        desc = explanation['description'].lower()
        if 'weight' in desc:
            print(f"- 텍스트 매칭 점수: {explanation['value']:.2f}")
        elif 'script score' in desc:
            print(f"- 벡터 유사도 점수: {explanation['value']:.2f}")
        elif 'sum of' in desc:
            print(f"- 총 유사도 점수: {explanation['value']:.2f}")
        elif 'product of' in desc:
            print(f"- 최종 유사도 점수: {explanation['value']:.2f}")

    if 'details' in explanation:
        for detail in explanation['details']:
            print_human_readable_explanation(detail)

def evaluate_answers(question, answer, years, job, type, combined_context, num_questions):
    if type == "technical":
        prompt = f"""
        # Role
        You are a technical interviewer with expertise in conducting interviews.

        # Task
        Evaluate the answer based on the following criteria:
        - Interviewer's job: {job}
        - Interviewer's experience level: {years} years
        - Interviewer's answer: {answer}
        - Question: {question}

        # Scoring Scale
        A: Correctly includes the concept of the technology mentioned in the question, as well as any additional correct information beyond that concept
        B: Correctly explains only the concept of the technology mentioned in the question
        C: Correctly explains any content about the technology mentioned in the question, even if not directly related to the question
        D: Correctly explains content about the field to which the technology mentioned in the question belongs
        E: Includes any correct technology-related content
        F: No answer, no technical content, or incorrect information

        # Instructions
        - Score strictly according to the 'Scoring Scale' above only.
        - For an 'A' score, the answer must correctly include the concept of the technology mentioned in the question, plus any additional correct information related to that technology. Always give an 'A' score if there's any correct information beyond the basic concept, regardless of its depth or amount.
        - Only assign scores based on correct information. If any part of the answer is incorrect, adjust the score accordingly.
        - Do not include any contents related to 'Scoring Scale' or score in the explanation.
        - Provide a model answer to the question, considering the interviewee's role and experience. This model answer should demonstrate the correct concept and include some additional correct information.
        - The model answer must consist only of content that can be verbally expressed. Do not include special characters such as hyphens or colons.
        - Evaluate the answer based on the following five criteria: problem-solving, technical understanding, logical thinking, learning ability, and collaboration/communication. Assign a score between 1 and 100 for each criterion.
        - If a criterion is not present in the answer, assign a null value, and only assign a score if the criterion is included.

        # Policy
        - Provide the explanation for the answer in Korean, focusing only on the technical content without mentioning the score or scoring criteria.
        - Generate a model answer in Korean, reflecting the content of your explanation.
        - The 'score' value must be expressed as an alphabetical letter.
        - Responses must be in JSON format.
        - Place the score in the `score` value of the JSON output.
        - Place the explanation in the `explanation` value of the JSON output.
        - Place the model answer in the `model` value of the JSON output.
        - Do not include any additional explanations beyond the specified output format.
        - Refer to users as '면접자'.

        # Output Format
        {{
            "score": "",
            "explanation": "",
            "model": "",
            "criteria_scores": {{
                "problem_solving": null,
                "technical_understanding": null,
                "logical_thinking": null,
                "learning_ability": null,
                "collaboration_communication": null
            }}
        }}
        """
    elif type == "behavioral":
        prompt = f"""
        # Absolute Chain-of-Thought Reasoning
        - Question Analysis: Analyze what personality traits the question is intended to evaluate.
        - Answer Analysis: Identify how the answer reflects the personality traits that need to be evaluated.
        - Detailed Evaluation: Explain how well the interviewee’s answer reflects the key personality traits.
        - Score Assignment: Assign an appropriate grade to the answer based on the evaluation criteria.
        
        # Abslute Role
        You are a character interviewer with expertise in conducting interviews.

        # Absolute Task
        - Evaluate the interviewee's response based on the following criteria:
          - **Job role**: {job}
          - **Years of experience**: {years}
          - **Interviewee's answer**: {answer}
          - **Interview question**: {question}
          
        # Absolute Policy
        - Responses must be in Korean.
        - In your answer, you should only consider the personality aspect and not the technical aspect.
        
        ## Absolute Evaluation Policy
        - You need to evaluate how the interviewee’s personal goals, values, and perspectives align with broader societal or professional objectives, and how they relate to their current job role.
        
        ## Absolute Score Policy
        - The score is placed in the "score" type in the JSON output.
        - Do not deviate from the grades provided in the "Grade" section.
        - The scoring must not be influenced by the scores given in the ## Absolute Criteria Scores Policy.
        
        ## Absolute Grade Policy
        - Assign a score to the response based on the following criteria:
            - If the answer is specific, logically well-structured, and sufficiently reflects the key personality elements required by the question, assign an “A” grade.
            - If the answer faithfully reflects key character elements with logical explanation, demonstrates a clear understanding of the topic, but does not require examples or experience, a grade of “B” will be awarded.
            - If the answer addresses some key elements but is general, lacks specificity, and fails to demonstrate a clear understanding, give it a grade of “C”
            - If the answer shows a lack of understanding of the key elements or lacks logical coherence, assign a "D" grade.
            - If the answer does not match the intent of the question but provides some related context, a grade of “E” will be given.
            - If the answer is missing, completely unrelated to the question, or explicitly indicates a lack of understanding of the question, assign an "F" grade.
                    
        ## Never Explanation Policy
        - The description must not mention any discussion.
                
        ## Absolute Explanation Policy
        - The explanation is placed in the "explanation" type of the JSON output.
        - The explanation should focus on evaluating how well the answer reflects the personality traits required by the question.
        - The explanation must clearly highlight the strengths and weaknesses of the answer, emphasizing areas for improvement.
        - Avoid discussing specific examples or mentioning the interviewee's personal experiences.
        - Do not mention scores or grades in the explanation.
        
        ## Absolute Intention Policy
        - Intention answers are placed in the "intention" type of the JSON output.
        - The value entered in “intention” must be written in Korean only.
        - The Intention must clearly reflect the general purpose of the question without explaining specific character traits.
        - The output should connect the intention to the following personality traits, depending on the context of the question: 
            - "honesty_reliability"
            - "interpersonal_skills"
            - "self_motivation_passion"
            - "adaptability"
            - "self_awareness"
        - Ensure that the intention briefly explains which of these traits are being assessed and how they relate to the question's objective.

        ## Absolute Criteria Scores Policy
        - In the "score scale" of JSON output, the value of each element type must be an integer between 1 and 100.
        
        ### Absolute Honesty and Reliability Policy
        - You need to evaluate how honest and trustworthy the answers are.
        - You should evaluate whether the answers honestly represent the interviewee's experience without exaggeration or inaccuracy.
        
        ### Absolute Interpersonal Skills Policy
        - In your answer you should assess how good your interpersonal skills are.
        - Scores must be assigned more strictly, reflecting the quality and depth of the answer in line with the expected standard.
        - A response that lacks detail, depth, or fails to demonstrate any relevant personality traits should receive a significantly lower score, potentially below 30.
        - The criteria scores must align with the overall grade assigned, ensuring consistency between individual element ratings and the final score.
        
        ### Absolute Self-Motivation and Passion Policy
        - We need to evaluate how well the respondent motivates himself and communicates his passion.
        
        ### Absolute Adaptability Policy
        - Assess your response to change and your ability to adapt to new environments.
        
        ### Absolute Self-Awareness Policy
        - Assess whether you are clear about your strengths and weaknesses.
        
        # Output Format
        {{
            "score": "",
            "explanation": "",
            "intention": "",
            "criteria_scores": {{
                "honesty_reliability": null,
                "interpersonal_skills": null,
                "self_motivation_passion": null,
                "adaptability": null,
                "self_awareness": null
            }}
        }}
        """
    else:
        raise ValueError("Invalid type provided. Must be 'technical' or 'behavioral'.")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {"role": "system", "content": "You are a professional interviewer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )

            response_content = completion.choices[0].message.content
            result = json.loads(response_content)

            # Ensure the evaluation score is a number
            if isinstance(result.get("score"), str) and result["score"].isdigit():
                result["score"] = int(result["score"])

            return result
        except json.JSONDecodeError as e:
            print(f"JSON 파싱 실패, 재시도 중... (시도 {attempt + 1}/{max_retries})")
            time.sleep(2)  # 짧은 대기 후 재시도

    # 모든 재시도 실패 시 기본 구조 반환
    return {"error": "JSONDecodeError"}

def evaluate_newQ(question: str, answer: str, years: str, job: str, type: str) -> dict:
    # type에 따라 INDEX_NAME 변경
    if type == 'technical':
        index_name = 'new_technology'
    elif type == 'behavioral':
        index_name = 'rag_behavioral'
    else:
        return {"error": "잘못된 type 값입니다. 'technical' 또는 'behavioral' 중 하나여야 합니다."}

    related_docs = searchDocs_evaluate(question, index_name, type)

    if related_docs:
        combined_context = " ".join(related_docs)
        num_questions = 10
        result = evaluate_answers(question, answer, years, job, type, combined_context, num_questions)
        print("@@@assessmentNewData", result)
        return result
    else:
        return {"Questions": ["문서를 찾지 못했습니다."]}