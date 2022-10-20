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
