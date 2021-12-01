import json
def getjson_dump(filename):
    with open(filename, "r") as jsonfile:
        jsondata = jsonfile.read()
    return json.loads(jsondata)