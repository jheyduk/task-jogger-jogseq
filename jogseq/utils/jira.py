from jira import JIRA, JIRAError


class Jira:
    
    def __init__(self, instance_url, user, api_token):
        
        self.api = JIRA(instance_url, basic_auth=(user, api_token))
        
        # Cache verification of issue IDs to reduce redundant lookups
        self._issue_key_cache = {}
    
    def verify_issue_id(self, issue_id):
        
        cache = self._issue_key_cache
        
        if issue_id not in cache:
            try:
                self.api.issue(issue_id, fields=['key'])
            except JIRAError as e:
                if e.status_code == 404:
                    cache[issue_id] = False
                else:
                    raise  # allow other errors to propagate
            else:
                cache[issue_id] = True
        
        return cache[issue_id]
    
    def get_issue_title(self, issue_id):
        
        try:
            issue = self.api.issue(issue_id, fields=['summary'])
        except JIRAError as e:
            # Ignore most problems fetching the Jira issue (connection issues,
            # authentication issues, etc) and just return a null name. But if
            # the issue ID is invalid, reflect that in the returned name.
            if e.status_code == 404:
                return '--- *invalid issue* ---'
            
            return None
        else:
            return issue.fields.summary
