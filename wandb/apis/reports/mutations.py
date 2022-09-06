from wandb_gql import gql

UPSERT_VIEW = gql(
    """
    mutation upsertView(
        $id: ID
        $entityName: String
        $projectName: String
        $type: String
        $name: String
        $displayName: String
        $description: String
        $spec: String!
    ) {
        upsertView(
        input: {
            id: $id
            entityName: $entityName
            projectName: $projectName
            name: $name
            displayName: $displayName
            description: $description
            type: $type
            createdUsing: WANDB_SDK
            spec: $spec
        }
        ) {
        view {
            id
            type
            name
            displayName
            description
            project {
                id
                name
            entityName
            }
            spec
            updatedAt
        }
        inserted
        }
    }
"""
)

CREATE_PROJECT = gql(
    """
    mutation upsertModel(
        $description: String
        $entityName: String
        $id: String
        $name: String
        $framework: String
        $access: String
        $views: JSONString
    ) {
        upsertModel(
        input: {
            description: $description
            entityName: $entityName
            id: $id
            name: $name
            framework: $framework
            access: $access
            views: $views
        }
        ) {
        project {
            id
            name
            entityName
            description
            access
            views
        }
        model {
            id
            name
            entityName
            description
            access
            views
        }
        inserted
        }
    }
"""
)
