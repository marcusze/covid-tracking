import time
import datetime

from flask import Flask, render_template, redirect, request, flash
from flask_table import Table, Col

import numpy as np

from neomodel import (config, StructuredNode, StringProperty, BooleanProperty, IntegerProperty,
    UniqueIdProperty, DateTimeProperty, RelationshipTo, RelationshipFrom, db)


#Todo: Change to os.environ('NEO4J_AUTH') 
config.DATABASE_URL = 'bolt://neo4j:neo123@172.17.0.1:7687' 
#config.ENCRYPTED_CONNECTION = False #For Neo4j 4.0+ as deafault is not encrypted
#check ip using $docker inspect neo4j-server
db.set_connection('bolt://neo4j:neo123@172.17.0.1:7687')

app = Flask(__name__)
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'


@app.route('/')
def home():
    tot = db.cypher_query("MATCH (N) return count(N)")
    n_rp = db.cypher_query("MATCH (N:RiskPatient) return count(N)")
    n_ct = db.cypher_query("MATCH (N:CareTaker) return count(N)")
    n_v = db.cypher_query("MATCH (N:Visit) return count(N)")
    

    return render_template('panel.html', nodes = tot[0][0][0], n_riskpatients=n_rp[0][0][0], n_caretakers=n_ct[0][0][0], n_visits=n_v[0][0][0])
    

#Reset the application
@app.route('/clear')
def clear():
    res = db.cypher_query("MATCH (n) DETACH DELETE n")
    return redirect('/')

#Run a simulation of visits
@app.route('/simulate', methods=['POST', 'GET'])
def simulate():
    startdate = datetime.datetime(2020,4,1)
    n_riskpatients = 50
    n_caretakers = 25
    visits_per_patient = 10
    visit_noise = 0.2

    if request.method == "POST":
        try:
            n_riskpatients = int(request.form.get('n_rp'))
            n_caretakers = int(request.form.get('n_ct'))
            visits_per_patient = int(request.form.get('n_v'))
            visit_noise = int(request.form.get('visit_noise'))/100
        except Exception as error:
            flash ("error" + str(error))
            time.sleep(2)
            return redirect('/')

    clear()
    for i in range(n_caretakers):
        caretaker = CareTaker(name="CT_"+str(i)).save()
    caretakers = CareTaker.nodes.all()

    for i in range(n_riskpatients):
        first_visit = Visit(date_time=startdate).save()
        first_visit.visited_by.connect(np.random.choice(caretakers))
        riskpatient = RiskPatient(name="RP_"+str(i), age=np.random.randint(60,100)).save()
        riskpatient.first_visit.connect(first_visit)
    
    riskpatients = RiskPatient.nodes.all()

    print("---Generate visits---")
    for riskpatient in riskpatients:
        prev_visit = riskpatient.first_visit.single()
        primary_caretaker = prev_visit.visited_by.single()
        
        for j in range(visits_per_patient-1):
            next_visit = Visit(date_time=startdate).save()
            prev_visit.next_visit.connect(next_visit)

            if np.random.random() < visit_noise:
                next_visit.visited_by.connect(np.random.choice(caretakers))
            else:
                next_visit.visited_by.connect(primary_caretaker)
            prev_visit = next_visit

    return redirect('/')

#Simulate transmissions
@app.route('/transmission', methods =['POST', 'GET'])
def transmission():

    n_asymptotic_carriers = 3
    transmission_prb = 0.2
    incubation_time = 4
    
    if request.method == 'POST':
        try:
            n_asymptotic_carriers = int(request.form.get('n_ac'))
            transmission_prb = int(request.form.get('transmission_prb'))/100
            incubation_time = int(request.form.get('incubation_time'))
        except Exception as error:
            flash ("error" + str(error))
            time.sleep(2)
            return redirect('/')

    caretakers = CareTaker.nodes.all()
    
    print("---Delete old flags---")
    db.cypher_query("""MATCH (n) WHERE n.flag=True SET n.flag=False Return n""")
    
    print("---Generate new transmissions---")
    asymptotic_carriers = np.random.choice(caretakers, size=n_asymptotic_carriers, replace=False)

    for ac in  asymptotic_carriers:
        ac.flag = True
        ac.save()
        for ac_visit in ac.get_visits_nhops_away(incubation_time):
            infected = np.random.random() < transmission_prb
            ac_visit.flag = infected
            ac_visit.save()
    n_visit_flags = len(Visit.nodes.filter(flag=True))

    return str(n_visit_flags) + " patients infected by " + str(n_asymptotic_carriers) + """ asymtomatic carriers 
                                            <br><b><a href = '/'><button>Back</button></a></b><br>"""

#Search for asymtomatic carriers
@app.route('/search')
def search():
    caretakers = CareTaker.nodes.all()
    infected_visits = Visit.nodes.filter(flag=True)

    for infected_visit in infected_visits:
        print(infected_visit.get_riskpatient())

    results, columns = db.cypher_query("""MATCH (v:Visit) WHERE v.flag=True 
                                        MATCH (prev:Visit)-[*]->(v) 
                                        MATCH (susp:CareTaker)<-[:VISITED_BY]-(prev)
                                        WITH susp,v
                                        Return DISTINCT susp as `Suspected carrier`, count(susp) as Count, collect(DISTINCT id(v)) as `Flags`
                                        ORDER BY Count DESC""")
    items =[]
    for row in results:
        caretaker = CareTaker.inflate(row[0])
        items += [dict(name=caretaker.name, ground_truth=caretaker.flag, count=row[1])] 
    table = ResultTable(items)

    return render_template('search_results.html', table = table)


class ResultTable(Table):
    classes = ['table', 'table-striped', 'table-bordered', 'table-condensed']
    name = Col('Caretaker')
    ground_truth = Col('Ground Truth')
    count = Col('Count of infected visits')

class RiskPatient(StructuredNode):
    uid = UniqueIdProperty()
    name = StringProperty(unique_index=True, default = "RP_"+ str(uid))
    age = IntegerProperty(index=True, default=0)
    first_visit = RelationshipTo('Visit', 'FIRST_VISIT')

class Visit(StructuredNode):
    #uid = UniqueIdProperty()
    date_time = DateTimeProperty()
    next_visit = RelationshipTo('Visit','NEXT')
    flag = BooleanProperty(default=False)
    visited_by = RelationshipTo('CareTaker', 'VISITED_BY')
    def get_riskpatient(self):
        results, columns = self.cypher("MATCH (a) WHERE id(a)={self} MATCH (rp:RiskPatient)-[*]->(a) RETURN rp LIMIT 1")
        return RiskPatient.inflate(results[0][0])

class CareTaker(StructuredNode):
    uid = UniqueIdProperty()
    name = StringProperty(unique_index=True, default = "CT_"+ str(uid))
    flag = BooleanProperty(default=False)

    def get_visits(self):
        results, columns = self.cypher("MATCH (a) WHERE id(a)={self} MATCH (a)<-[:VISITED_BY]-(v:Visit) RETURN v")
        return [self.inflate(row[0]) for row in results]

    def get_visits_nhops_away(self, nhops):
        assert type(nhops)==int
        results, columns = self.cypher("MATCH (a) WHERE id(a)={self} MATCH (a)<-[:VISITED_BY]-(v:Visit) MATCH (v)-[:NEXT*"+ str(nhops)+ "]->(vn) RETURN vn")
        return [Visit.inflate(row[0]) for row in results]

if __name__ == '__main__':
   app.run(debug=True)
    