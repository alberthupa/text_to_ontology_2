you are in a folder of a project which is a beginning of a text to graph app. 
read AGENTS.md, README.md and files in "docs" folder.
it kinda does basic things i want. but now this is a bit of collection of loose files.
i want you to propose initial architecture for it. main aim that i want to achieve is: modularity and api like structure, where a flow is oriented around modules that do their things and every module is kinda independent, and their common currency is graph / ttl / sparql. so every module takes as input graph, some params, and these ealy steps: text of course.
right now text input is either one file or a dir. we will have to accomodate for a situation in which an input text will be super long and will have to be windowed somethow.
We will in the future definitely want to pamatrize how graph skeleton is taken into the graph because i envision that input texts will be longer
* replace ttl with jena or something like this - currently this is just loading ttl file, but we have to assume that both the main graph will be bigger and bigger, and as input in the future there will be many graphs / shacl shapes
* later we will want separate tool for building seed graph
* some kind of a backlog is in docs/ox_recommendations.md


### other rules
* keep it simple, keep it stupid
* code and names must be self explanatory for a user. human readability is more important than some sohpsticated coding guidelines
* in scope of semantic technologies i want to stick to vanilla rdf, rdfs, owl, skos, shacl solutions (and using of some most common vocabularies like foaf and others), but nothing custom!

### final thing
do not change any code, just write your architecture proposal. save your answer in architecture_proposal_deepseek.md in docs folder

