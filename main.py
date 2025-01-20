import os
import requests
import json
from openai import OpenAI
from easy_rag import RagService
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed


load_dotenv()
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
openai_api_key = os.getenv("OPENAI_API_KEY")


### Set QA model.
### deepseek-chat is default. You can set gpt-3.5-turbo as well.

def generate_qa_prompt(claim: str):
    return f"""
    The following is a claim provided by the user. Generate detailed questions needed to evaluate the validity of the claim. 
    Each question should help assess the logical basis, support or refute the claim, and actively explore counterexamples. 
    The generated questions should be output in python list format, with each question written as a single sentence. 
    Limit the number of questions to 10 or fewer.
    ===== Provided Claim (Start) =====
    {claim}
    ===== Provided Claim (End) =====

    Input Format:
    "<text containing the claim>"

    Output Format:
    "<a sentence containing the purpose and content of the question>", \n
    ...

    Example Input:
    "Electric cars are more environmentally friendly."

    Example Output:
    "Scientific basis verification: How much lower is the carbon footprint of electric car production compared to internal combustion engine cars?",
    "Counterexample exploration: What are some examples of environmental issues caused by electric car battery waste?",
    "Relevant data verification: What research results compare the environmental impact of electric and internal combustion engine cars over their lifecycle?"
    """

def qa_model(claim: str, model: str = "deepseek-chat"):
    print("주장을 판단하기 위한 세부질문을 생성중입니다...")
    if model == "deepseek-chat":
        headers = {
            "Authorization": f"Bearer {deepseek_api_key}",
            "Content-Type": "application/json"
        }
        try:
            response = requests.post(
                url=f"{deepseek_base_url}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": generate_qa_prompt(claim)}],
                    "max_tokens": 1500,
                    "temperature": 0.9
                }
            )
            response.raise_for_status()
            data = response.json()
            if "choices" not in data or not data["choices"]:
                raise ValueError("DeepSeek API에서 올바르지 않은 응답 형식이 반환되었습니다.")
            
            # 응답 내용 가져오기
            content = data["choices"][0]["message"]["content"].strip()
            
            # 코드 블록 제거
            if content.startswith("```") and content.endswith("```"):
                content = content[content.find("\n") + 1:content.rfind("\n")].strip()
            
            try:
                # JSON 형식으로 파싱 시도
                questions = json.loads(content)
                if not isinstance(questions, list):
                    raise ValueError("DeepSeek 응답이 리스트 형식이 아닙니다.")
                return questions
            except json.JSONDecodeError:
                # JSON 파싱 실패 시 개행으로 분리
                return [q.strip() for q in content.split("\n") if q.strip()]
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"DeepSeek API 호출 실패: {e}")
        except ValueError as e:
            raise RuntimeError(f"DeepSeek 응답 처리 실패: {e}")

    elif model == "gpt-3.5-turbo":
        client = OpenAI(api_key=openai_api_key)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": generate_qa_prompt(claim)}
                ],
                max_tokens=1500,
                temperature=0.9 
            )
            content = response.choices[0].message.content.strip()
            
            # 코드 블록 제거
            if content.startswith("```") and content.endswith("```"):
                content = content[content.find("\n") + 1:content.rfind("\n")].strip()
            
            return [q.strip() for q in content.split("\n") if q.strip()]
        except Exception as e:
            raise RuntimeError(f"답변 생성 중 오류 발생: {e}")
    else:
        raise ValueError("지원하지 않는 모델입니다.")
    
### Jury Agent
### Set easy-rag-llm.
def process_question(rs, resource, question, original_claim):
    jury_prompt = f"""
    You are a juror tasked with preparing a logical and well-reasoned response to the derived sub-question "{question}" in order to evaluate the original question "{original_claim}".
    Carefully review the provided materials and base your evaluation and response strictly on the evidence presented.
    1) All responses and evaluations must be grounded solely in the provided materials.
    2) Do not reference or rely on any information or evidence not included in the materials.
    3) Your response will serve as a critical basis for determining the truthfulness of the original question "{original_claim}".
    """
    response, evidence = rs.generate_response(resource, question, evidence_num=5)
    return question, response, evidence

def jury_agent(questions: list, original_claim: str):
    print("생성된 세부 질문들이 배심원단에 의해 판단되는 중입니다...")
    rs = RagService(
        embedding_model="text-embedding-3-small",
        response_model="deepseek-chat",
        open_api_key=openai_api_key,
        deepseek_api_key=deepseek_api_key,
        deepseek_base_url=deepseek_base_url,
    )
    print("배심원단이 문서에서 근거를 찾는 중입니다...")
    resource = rs.rsc("./rscFiles", force_update=False, max_workers=15)  # 전체 문서 임베딩
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_question, rs, resource, question, original_claim): question
            for question in questions
        }
        for future in as_completed(futures):
            question = futures[future]
            try:
                question, response, evidence = future.result()
                print(f"Question: {question}")
                print(f"Response: {response}")
                print(f"Evidence: {evidence}")
                print("\n=====================================================\n")
            except Exception as e:
                print(f"Error processing question '{question}': {e}")



if __name__ == "__main__":
    """ QA 모델 테스트
    ### TEST ###
    claim = "Electric cars are more environmentally friendly."
    model = "deepseek-chat"
    print(qa_model(claim, model))
    """
    claim = "지구 온난화는 기후 모델이 예측한 만큼 진행되지 않고 있다. 이는 식물의 광합성이 예상보다 더 많은 CO2를 흡수하고 있기 때문이다. 기후 변화는 거짓말이다."
    model = "deepseek-chat"
    questions = qa_model(claim,model)

    jury_agent(questions, claim)







