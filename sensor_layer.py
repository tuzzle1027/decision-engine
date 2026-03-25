# ===============================
# sensor_layer.py
# 의도 / 반의도 / 갈등 / 저항 / 제약
# 동현님 설계 / 로드 구현
# ===============================
# 논문 공식 전부 반영
# [의도]  Drive{N,W,Ψ} / S₁S₂ / R=f(C₁~C₅) / Φ / Ĩ=g(R,Φ)
# [반의도] 스캔루프선검사 / Aₛ=αN+βR+γDₗ / D=I-A 안정구간
# [갈등]  C=(C₁~C₆) / P(D=1)=exp(...) / top2축
# [저항]  A가속/B브레이크/D핸들 / Direction=A-D / Speed=A-B / R₂비선형
# [제약]  Rᵢ=IᵢPᵢUᵢ / Sigmoid / θc=θ₀+αF+βL / Always On
# ===============================
import re, math

# ── 의도 패턴 ──
S2_PATTERNS  = r'(사고싶|찾아요|추천해줘|구매하|필요해|사려고|알아보|사고 싶|찾고 있|buy|purchase|looking for|want to buy|need)'
NEED_PATTERNS = r'(필요|없어서|불편|꼭|써야|고장|해결|must|need|broken|required)'
WANT_PATTERNS = r'(갖고 싶|원해|이왕이면|좋은 걸|갖고싶|사고싶|원하|이런 느낌|want|wish|prefer|ideally)'
PSI_PATTERNS  = r'(있어보이|세련|명품|프리미엄|고급|남들|사람들|보기|이미지|느낌|분위기|luxury|premium|stylish|look good)'
C1_P = r'(구체적으로|정확히|자세히|특히|specifically|exactly|precisely)'
C2_P = r'(너무|진짜|정말|꼭|완전|싫|좋|very|really|absolutely|hate|love)'
C3_P = r'(그리고|근데|하지만|말고|또|and|but|also|however|plus)'
C4_P = r'(다시|또|재질문|한번더|again|once more)'
C5_P = r'(vs|아니면|둘중|비교|어떤게|or|versus|which one|compare)'
PHI_URGENT  = r'(급|빨리|지금 당장|오늘|내일까지|urgent|asap|right now|today)'
PHI_EXPLORE = r'(그냥|혹시|궁금|어떤지|한번|just|curious|wondering|maybe)'
PHI_READY   = r'(살거야|결정했|구매 예정|이미|decided|will buy|going to)'

def classify_S(text):
    return 'S2' if re.search(S2_PATTERNS, text, re.IGNORECASE) else 'S1'

def detect_drive(text):
    N=bool(re.search(NEED_PATTERNS,text,re.IGNORECASE))
    W=bool(re.search(WANT_PATTERNS,text,re.IGNORECASE))
    Psi=bool(re.search(PSI_PATTERNS,text,re.IGNORECASE))
    return {'N':N,'W':W,'Psi':Psi,'dominant':'Psi' if Psi else('W' if W else('N' if N else 'unknown'))}

def calculate_R(text):
    C1=len(re.findall(C1_P,text,re.IGNORECASE))*0.4
    C2=len(re.findall(C2_P,text,re.IGNORECASE))*0.5
    C3=len(re.findall(C3_P,text,re.IGNORECASE))*0.3
    C4=len(re.findall(C4_P,text,re.IGNORECASE))*0.3
    C5=len(re.findall(C5_P,text,re.IGNORECASE))*0.5
    R=C1+C2+C3+C4+C5
    return {'R':round(R,2),'C1':round(C1,2),'C2':round(C2,2),'C3':round(C3,2),'C4':round(C4,2),'C5':round(C5,2)}

def calculate_Phi(text):
    if re.search(PHI_READY,text,re.IGNORECASE): return 1.5
    if re.search(PHI_URGENT,text,re.IGNORECASE): return 1.4
    if re.search(S2_PATTERNS,text,re.IGNORECASE): return 1.2
    if re.search(PHI_EXPLORE,text,re.IGNORECASE): return 0.6
    return 0.8

def estimate_I_hat(R_score,Phi):
    I=R_score*Phi
    return {'I_hat':round(I,2),'theta':1.0,'activated':I>1.0}

# ── 반의도 ──
NEG_SIGNALS=['별로','마음에 안','아니에요','싫어요','안 좋아','비싸','멀어','불편','실망','후회','괜히','not good','dont like','too expensive','bad','dislike']
B_ANTI={'B1':r'(고민|확신|모르겠|애매|불안|괜찮을까|맞는지|unsure|not sure|maybe)','B2':r'(더 찾아|또 없나|다른 거|조금 더|비슷한|another|more|keep looking)','B3':r'(나중에|생각해볼|천천히|급하지|보류|later|think about|no rush)'}

def is_scan_loop(text,condition_added=False):
    scan=['다른 거','또 알려줘','더 없나','다른 데','another','more options']
    has_scan=any(s in text for s in scan)
    no_neg=not bool(re.search(r'(별로|마음에 안|비싸|싫|not good)',text))
    return sum([has_scan,no_neg,not condition_added])>=2

def detect_N_anti(text):
    return round(min(sum(1 for s in NEG_SIGNALS if s in text.lower())*0.3,1.0),2)

def detect_R_anti(rej):
    return 0.8 if rej>=3 else(0.5 if rej>=2 else(0.2 if rej>=1 else 0.0))

def detect_Dl(turns,cond=False):
    if cond: return 0.0
    return 0.6 if turns>=5 else(0.3 if turns>=3 else 0.0)

def calculate_As(text,rej=0,turns=0,cond=False,hi=False):
    N=detect_N_anti(text); R=detect_R_anti(rej); Dl=detect_Dl(turns,cond)
    a,b,g=(0.6,0.3,0.1) if hi else(0.5,0.3,0.2)
    return round(min(a*N+b*R+g*Dl,1.0),2)

def check_stability(I,As):
    D=round(I-As,2)
    st='마비' if D<0 else('고민중' if D<0.3 else('충동' if D>2.0 else '안정'))
    return {'D':D,'state':st}

def get_anti_intervention(As):
    if As>=0.70: return {'level':'HIGH','action':'보류허용','message':'지금 당장 결정 안 하셔도 됩니다.'}
    elif As>=0.45: return {'level':'MEDIUM','action':'축탐색질문','message':'시설/가격/거리 중 어떤 게 제일 중요하세요?'}
    return {'level':'LOW','action':None,'message':None}

def anti_intent_engine(text,I_hat=0,rej=0,turns=0,cond=False,hi=False):
    if is_scan_loop(text,cond):
        return {'type':'SCAN_LOOP','As':0.0,'intervention':{'level':'SCAN','action':'기준형성_질문','message':'분위기/가성비/위치 중 어떤 게 중요하세요?'},'stability':None}
    As=calculate_As(text,rej,turns,cond,hi)
    return {'type':'ANTI_INTENT','As':As,'N':detect_N_anti(text),'R':detect_R_anti(rej),'Dl':detect_Dl(turns,cond),'intervention':get_anti_intervention(As),'stability':check_stability(I_hat,As)}

# ── 갈등 6축 ──
CONFLICT_DICT={'C1_safety':['안전','소재','마감','냄새','친환경','걱정','위험','safety','risk'],'C2_function':['각도','고정','미끄럼','자세','집중','효과','기능','성능','사용성','performance'],'C3_timing':['지금','얼마나','성장','언제','미리','오래','시기','now','when','how long'],'C4_delivery':['배송','도착','기간','파손','리드타임','언제 와','delivery','shipping'],'C5_price':['비싸','가성비','부담','쿠폰','할인','돈값','투자','expensive','price','worth'],'C6_compare':['다른 거','비교','후기','브랜드','vs','대안','compare','alternative']}

def conflict_engine(text):
    vector={k:0 for k in CONFLICT_DICT}; signals=[]
    for axis,kws in CONFLICT_DICT.items():
        for kw in kws:
            if kw in text.lower(): vector[axis]+=1; signals.append(f'{axis}:{kw}')
    total=sum(vector.values())
    return {'Conflict_Total':total,'Conflict_Vector':vector,'Hesitation':'HIGH' if total>=4 else('MEDIUM' if total>=2 else 'LOW'),'signals':signals}

def top_conflict_axes(vector,n=2):
    return sorted(vector.items(),key=lambda x:x[1],reverse=True)[:n]

def decision_probability(C,mu=3.0,sigma=2.0):
    return round(math.exp(-((C-mu)**2)/(2*sigma**2)),3)

# ── 저항 자동차 모델 ──
A_PAT=r'(사고싶|해야|가야|필요해|구매|원해|하고싶|결정했|살거야|want|need|must|will buy)'
D_PAT=r'(싫어|안 할|아닌것|그건 아니|별로|no|dont want|not that)'
B_PAT={'B1':r'(고민|확신|모르겠|애매|불안|괜찮을까|맞는지|unsure|not sure|maybe)','B2':r'(더 찾아|또 없나|다른 거|조금 더|비슷한|another|more|keep looking)','B3':r'(나중에|생각해볼|천천히|급하지|보류|later|think about|no rush)'}

def detect_A(text): return round(min(len(re.findall(A_PAT,text,re.IGNORECASE))*0.4,1.0),2)
def detect_D_res(text): return round(min(len(re.findall(D_PAT,text,re.IGNORECASE))*0.5,1.0),2)
def detect_B(text):
    B1=len(re.findall(B_PAT['B1'],text,re.IGNORECASE))*0.4
    B2=len(re.findall(B_PAT['B2'],text,re.IGNORECASE))*0.3
    B3=len(re.findall(B_PAT['B3'],text,re.IGNORECASE))*0.3
    return {'B_total':round(min(B1+B2+B3,1.0),2),'B1':round(min(B1,1.0),2),'B2':round(min(B2,1.0),2),'B3':round(min(B3,1.0),2)}

def calculate_R2(B,theta=0.5,alpha=0.8):
    return round(B if B<theta else B+alpha*(B-theta)**2,2)

def classify_res_state(direction,speed):
    if direction<=0: return 'ANTI_INTENT'
    elif speed<=0.2: return 'RESISTANCE'
    return 'INTENT'

def get_res_intervention(B_detail,R2,theta=0.5):
    if R2<theta: return {'level':'NONE','action':None}
    dominant=max([('B1',B_detail['B1']),('B2',B_detail['B2']),('B3',B_detail['B3'])],key=lambda x:x[1])[0]
    if dominant=='B2': return {'level':'MEDIUM','type':'정보저항','action':'비교개입','template':'두 제품의 핵심 차이는 {축}입니다.','effect':'B낮춤'}
    elif dominant=='B1': return {'level':'MEDIUM','type':'확신저항','action':'적합성확인','template':'{목적}이라면 이 모델이 더 적합합니다.','effect':'A강화'}
    return {'level':'HIGH','type':'책임저항','action':'선택압축','template':'지금 상황에서는 이 두 가지 중 하나가 가장 합리적입니다.','effect':'B낮춤'}

def resistance_engine(text,theta=0.5):
    A=detect_A(text); Br=detect_B(text); D=detect_D_res(text); B=Br['B_total']
    direction=round(A-D,2); speed=round(A-B,2); R2=calculate_R2(B,theta)
    state=classify_res_state(direction,speed)
    return {'A':A,'B':B,'D':D,'Direction':direction,'Speed':speed,'R2':R2,'state':state,'intervention':get_res_intervention(Br,R2,theta),'B_detail':Br}

# ── 제약 Always On ──
CONSTRAINT_CATALOG={'C1_money':{'I':0.8,'keywords':['비용','요금','초과','벌금','수수료','cost','fee','penalty']},'C2_time':{'I':0.6,'keywords':['마감','기한','배송','늦','일정','deadline','late','schedule']},'C3_health':{'I':0.9,'keywords':['알레르기','위험','유해','건강','부작용','allergy','risk','health']},'C4_legal':{'I':0.95,'keywords':['법','규정','위반','불법','계약','law','regulation','illegal']},'C5_rep':{'I':0.5,'keywords':['평판','이미지','후기','신뢰','reputation','trust','review']}}

def constraint_engine(text,confirmed=None,F_prev=0,L_prev=0):
    if confirmed is None: confirmed={}
    theta_c=round(min(0.4+0.1*F_prev+0.05*L_prev,0.9),3)
    risks={}; interventions=[]
    for key,c in CONSTRAINT_CATALOG.items():
        P=round(min(sum(1 for kw in c['keywords'] if kw in text)*0.35,1.0),2)
        U=0.0 if confirmed.get(key,False) else 1.0
        R=round(c['I']*P*U,3); risks[key]=R
        if R>theta_c:
            interventions.append({'constraint':key,'R':R,'intensity':round(1/(1+math.exp(-8*(R-theta_c))),3)})
    interventions.sort(key=lambda x:x['R'],reverse=True)
    return {'theta_c':theta_c,'risk_scores':risks,'top_risks':sorted(risks.items(),key=lambda x:x[1],reverse=True)[:2],'interventions':interventions,'silent':len(interventions)==0}

# ── 통합 센서 레이어 ──
def sensor_layer(raw_text, session=None):
    if session is None: session={}
    # 의도
    S_type=classify_S(raw_text); drive=detect_drive(raw_text)
    R_result=calculate_R(raw_text); Phi=calculate_Phi(raw_text)
    I_result=estimate_I_hat(R_result['R'],Phi)
    # 반의도
    anti=anti_intent_engine(raw_text,I_hat=I_result['I_hat'],rej=session.get('rejection_count',0),turns=session.get('turn_count',0),cond=session.get('condition_added',False),hi=session.get('high_involvement',False))
    # 갈등
    conflict=conflict_engine(raw_text)
    P_dec=decision_probability(conflict['Conflict_Total'])
    top_axes=top_conflict_axes(conflict['Conflict_Vector'])
    # 저항
    resistance=resistance_engine(raw_text)
    # 제약
    constraint=constraint_engine(raw_text,F_prev=session.get('fatigue',0),L_prev=session.get('intervention_count',0))

    return {
        # 의도
        'S_type':S_type,'Drive':drive,'R':R_result['R'],'R_detail':R_result,'Phi':Phi,'I_hat':I_result['I_hat'],'activated':I_result['activated'],
        # 반의도
        'anti_type':anti['type'],'As':anti.get('As',0),'anti_N':anti.get('N',0),'anti_R':anti.get('R',0),'anti_Dl':anti.get('Dl',0),'anti_intervention':anti['intervention'],'stability':anti.get('stability'),
        # 갈등
        'Conflict':conflict['Conflict_Total'],'Conflict_Vector':conflict['Conflict_Vector'],'Conflict_signals':conflict['signals'],'Hesitation':conflict['Hesitation'],'P_decision':P_dec,'top_axes':top_axes,
        # 저항
        'A':resistance['A'],'B':resistance['B'],'D':resistance['D'],'Direction':resistance['Direction'],'Speed':resistance['Speed'],'R2':resistance['R2'],'res_state':resistance['state'],'res_intervention':resistance['intervention'],
        # 제약
        'constraint_silent':constraint['silent'],'constraint_interventions':constraint['interventions'],'constraint_risks':constraint['risk_scores'],'constraint_top':constraint['top_risks'],
    }
