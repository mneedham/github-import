# pulling repositories from this API endpoint: https://api.github.com/search/repositories
import json
import os
import datetime
import requests
import boto3
import time

from datetime import tzinfo, timedelta

ZERO = timedelta(0)


class UTC(tzinfo):
    def utcoffset(self, dt):
        return ZERO

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return ZERO


utc = UTC()

from base64 import b64decode
from neo4j.v1 import GraphDatabase, basic_auth
from dateutil import parser


def lambda_handler(event, context):
    print("Event:", event)
    version_updated = "Default (Updating public graph)"
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', "test")
    NEO4J_URL = os.environ.get('NEO4J_URL', "bolt://localhost")

    if event and event.get("resources"):
        if "CommunityGraphGitHubImport" in event["resources"][0]:
            version_updated = "Updating public graph"
            ENCRYPTED_NEO4J_PASSWORD = os.environ['NEO4J_PASSWORD']
            NEO4J_PASSWORD = boto3.client('kms').decrypt(CiphertextBlob=b64decode(ENCRYPTED_NEO4J_PASSWORD))['Plaintext']
            NEO4J_URL = os.environ.get('NEO4J_PUBLIC_URL')
        elif "CommunityGraphGitHubImportPrivate" in event["resources"][0]:
            version_updated = "Updating private graph"
            ENCRYPTED_NEO4J_PASSWORD = os.environ['NEO4J_PRIVATE_PASSWORD']
            NEO4J_PASSWORD = boto3.client('kms').decrypt(CiphertextBlob=b64decode(ENCRYPTED_NEO4J_PASSWORD))['Plaintext']
            NEO4J_URL = os.environ.get('NEO4J_PRIVATE_URL')

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
     repo.watchers = r.watchers, repo.language = r.language, repo.forks = r.forks_count,
    repo.open_issues = r.open_issues, repo.branch = r.default_branch, repo.description = r.description
    MERGE (owner:User:GitHub {id:r.owner.id}) SET owner.name = r.owner.login, owner.type=r.owner.type, owner.full_name = r.owner.name
    MERGE (owner)-[:CREATED]->(repo)
    """

    # importQuery = """
    #     WITH {json} as data
    #     UNWIND data.items as r
    #     RETURN r.name, r.full_name, r.html_url, apoc.date.parse(r.created_at,'ms',"yyyy-MM-dd'T'HH:mm:ss'Z'"), r.created_at, r.homepage,
    #     r.stargazers_count, apoc.date.parse(r.updated_at,'ms',"yyyy-MM-dd'T'HH:mm:ss'Z'"), r.updated_at, r.pushed_at,  r.size, r.score,
    #     r.watchers, r.language, r.forks_count, r.open_issues, r.default_branch, r.description, r.owner.id, r.owner.login, r.owner.type, r.owner.name
    #     LIMIT 10
    #     """

    from_date = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")

    print("Processing projects from {0}".format(from_date))

    search="neo4j pushed:>{0}".format(from_date)
    cursor=None
    has_more=True

    while has_more:
        apiUrl = "https://api.github.com/graphql"

        data = {
            "query": """\
               query  Repositories($searchTerm: String!, $cursor: String) {
                 rateLimit {
                    limit 
                    cost
                    remaining
                    resetAt
                 }
                 search(query:$searchTerm, type: REPOSITORY, first: 100, after: $cursor) {
                   repositoryCount
                   pageInfo {
                        hasNextPage
                        endCursor
                   }
                   nodes {
                     __typename
                     ... on Repository {
                       databaseId
                       name
                       url       
                       pushedAt
                       createdAt
                       updatedAt
                       diskUsage
                       description
                       homepageUrl
                       issues {
                         totalCount
                       }
                       stargazers {
                         totalCount
                       }
                       watchers {
                         totalCount
                       }
                       forks { 
                           totalCount
                       }
                       
                       languages(first:1, orderBy: {field: SIZE, direction:DESC}) {
                         nodes {
                           name
                         }
                       }
                       owner {          
                         __typename
                         login                         
                         ... on User {
                           name
                           databaseId
                         }
                         ... on Organization {
                            name
                            databaseId
                         }
                       }    
                        defaultBranchRef {
                          name
                        }
                     }      
                   }
                 }
               }
            """,
            "variables": {"searchTerm": search, "cursor": cursor}
        }

        response = requests.post(apiUrl, data = json.dumps(data), headers = {"accept":"application/json", "Authorization": "bearer 5091787e0bc786368c503d31f10aae2b589be309"})
        r = response.json()

        the_json = []
        search_section = r["data"]["search"]
        for node in search_section["nodes"]:
            languages = [n["name"] for n in node["languages"]["nodes"]]
            default_branch_ref = node.get("defaultBranchRef") if node.get("defaultBranchRef") else {}

            params = {
                "id": node["databaseId"],
                "name": node["name"],
                "full_name": "{login}/{name}".format(name=node["name"], login=node["owner"]["login"]),
                "created_at": node["createdAt"],
                "pushed_at": node["pushedAt"],
                "updated_at": node["updatedAt"],
                "size": node["diskUsage"],
                "homepage": node["homepageUrl"],
                "stargazers_count": node["forks"]["totalCount"],
                "forks_count": node["stargazers"]["totalCount"],
                "watchers": node["watchers"]["totalCount"],
                "owner": {
                    "id": node["owner"].get("databaseId", ""),
                    "login": node["owner"]["login"],
                    "name": node["owner"].get("name", ""),
                    "type": node["owner"]["__typename"]
                },
                "default_branch": default_branch_ref.get("name", ""),
                "open_issues": node["issues"]["totalCount"],
                "description": node["description"],
                "html_url": node["url"],
                "language": languages[0] if len(languages) > 0 else ""
            }

            the_json.append(params)

        has_more = search_section["pageInfo"]["hasNextPage"]
        cursor = search_section["pageInfo"]["endCursor"]

        result = session.run(importQuery, {"json": {"items": the_json}})
        print(result.consume().counters)

        reset_at = r["data"]["rateLimit"]["resetAt"]
        time_until_reset = (parser.parse(reset_at) - datetime.datetime.now(utc)).total_seconds()

        if r["data"]["rateLimit"]["remaining"] <= 0:
            time.sleep(time_until_reset)

        print("Reset at:", time_until_reset, "has_more", has_more, "cursor", cursor, "repositoryCount", search_section["repositoryCount"])

    session.close()


if __name__ == "__main__":
    neo4jPass = os.environ.get('NEO4J_PASSWORD', "neo")
    neo4jUrl = os.environ.get('NEO4J_URL', "bolt://localhost")
    neo4jUser = os.environ.get('NEO4J_USER', "neo4j")

    import_github(neo4jUrl=neo4jUrl, neo4jUser=neo4jUser, neo4jPass=neo4jPass)
