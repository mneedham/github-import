# pulling repositories from this API endpoint: https://api.github.com/search/repositories

import os
import datetime
import requests
import boto3
import time

from base64 import b64decode
from neo4j.v1 import GraphDatabase, basic_auth

def lambda_handler(event, context):
    print("Event:", event)
    version_updated = "Default (Updating GraphQL graph)"
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', "test")
    NEO4J_URL = os.environ.get('NEO4J_URL', "bolt://localhost")

    if event and event.get("resources"):
        if "GraphQLCommunityGraphGitHubImport" in event["resources"][0]:
            ENCRYPTED_NEO4J_PASSWORD = os.environ['NEO4J_PASSWORD']
            NEO4J_PASSWORD = boto3.client('kms').decrypt(CiphertextBlob=b64decode(ENCRYPTED_NEO4J_PASSWORD))['Plaintext']
            NEO4J_URL = os.environ.get('NEO4J_URL')

    neo4jUrl = NEO4J_URL
    neo4jPass = NEO4J_PASSWORD
    neo4jUser = os.environ.get('NEO4J_USER', "neo4j")

    print(version_updated)
    import_github(neo4jUrl=neo4jUrl, neo4jUser=neo4jUser, neo4jPass=neo4jPass)

def import_github(neo4jUrl, neo4jUser, neo4jPass):
    driver = GraphDatabase.driver(neo4jUrl, auth=basic_auth(neo4jUser, neo4jPass))

    session = driver.session()

    # Build query.
    importQuery = """
    WITH {json} as data
    UNWIND data.items as r
    MERGE (repo:Repository:GitHub {id:r.id})
      ON CREATE SET repo.title = r.name, repo.full_name=r.full_name, repo.url = r.html_url, repo.created = apoc.date.parse(r.created_at,'ms',"yyyy-MM-dd'T'HH:mm:ss'Z'"), repo.created_at = r.created_at,
      repo.homepage = r.homepage
    SET repo.favorites = r.stargazers_count, repo.updated = apoc.date.parse(r.updated_at,'ms',"yyyy-MM-dd'T'HH:mm:ss'Z'"), repo.updated_at = r.updated_at, repo.pushed = r.pushed_at,repo.size = r.size,
     repo.score = r.score, repo.watchers = r.watchers, repo.language = r.language, repo.forks = r.forks_count,
    repo.open_issues = r.open_issues, repo.branch = r.default_branch, repo.description = r.description

    MERGE (owner:User:GitHub {id:r.owner.id}) ON CREATE SET owner.name = r.owner.login, owner.type=r.owner.type
    MERGE (owner)-[:CREATED]->(repo)
    """

    page=1
    items=100
    tag="Neo4j"
    hasMore=True

    from_date = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")

    print("Processing projects from {0}".format(from_date))

    search="graphql%20pushed:>{0}".format(from_date)
    page=1
    items=100
    hasMore=True
    total=0

    while hasMore == True:
        # Build URL.
        # TODO authenticated request
        apiUrl = "https://api.github.com/search/repositories?q={search}&fork=only&page={page}&per_page={items}".format(search=search,items=items,page=page)
    #    if maxDate <> None:
    #        apiUrl += "&min={maxDate}".format(maxDate=maxDate)
        response = requests.get(apiUrl, headers = {"accept":"application/json"})
        if response.status_code != 200:
            print(response.status_code,response.text)
        json = response.json()
        total = json.get("total_count",0)
    #    total = 100
        if json.get("items",None) != None:
            print(len(json["items"]))
            result = session.run(importQuery,{"json":json})
            print(result.consume().counters)
            page = page + 1

        hasMore = page * items < total
        print("hasMore",hasMore,"page",page,"total",total)

    #    if json.get('quota_remaining',0) <= 0:
        time.sleep(10)
    #    if json.get('backoff',None) != None:
    #        print("backoff",json['backoff'])
    #        time.sleep(json['backoff']+5)

    session.close()


if __name__ == "__main__":
    neo4jPass = os.environ.get('NEO4J_PASSWORD', "test")
    neo4jUrl = os.environ.get('NEO4J_URL', "bolt://localhost")
    neo4jUser = os.environ.get('NEO4J_PASSWORD', "test")

    import_github(neo4jUrl=neo4jUrl, neo4jUser=neo4jUser, neo4jPass=neo4jPass)
