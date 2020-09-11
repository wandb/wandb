from graphql.type import (GraphQLArgument, GraphQLEnumType, GraphQLEnumValue,
                          GraphQLField, GraphQLInterfaceType, GraphQLList,
                          GraphQLNonNull, GraphQLObjectType, GraphQLSchema,
                          GraphQLString)

from .fixtures import getDroid, getFriends, getHero, getHuman

episodeEnum = GraphQLEnumType(
    'Episode',
    description='One of the films in the Star Wars Trilogy',
    values={
        'NEWHOPE': GraphQLEnumValue(
            4,
            description='Released in 1977.',
        ),
        'EMPIRE': GraphQLEnumValue(
            5,
            description='Released in 1980.',
        ),
        'JEDI': GraphQLEnumValue(
            6,
            description='Released in 1983.',
        )
    }
)

characterInterface = GraphQLInterfaceType(
    'Character',
    description='A character in the Star Wars Trilogy',
    fields=lambda: {
        'id': GraphQLField(
            GraphQLNonNull(GraphQLString),
            description='The id of the character.'
        ),
        'name': GraphQLField(
            GraphQLString,
            description='The name of the character.'
        ),
        'friends': GraphQLField(
            GraphQLList(characterInterface),
            description='The friends of the character, or an empty list if they have none.'
        ),
        'appearsIn': GraphQLField(
            GraphQLList(episodeEnum),
            description='Which movies they appear in.'
        ),
    },
    resolve_type=lambda character, *_: humanType if getHuman(character.id) else droidType,
)

humanType = GraphQLObjectType(
    'Human',
    description='A humanoid creature in the Star Wars universe.',
    fields=lambda: {
        'id': GraphQLField(
            GraphQLNonNull(GraphQLString),
            description='The id of the human.',
        ),
        'name': GraphQLField(
            GraphQLString,
            description='The name of the human.',
        ),
        'friends': GraphQLField(
            GraphQLList(characterInterface),
            description='The friends of the human, or an empty list if they have none.',
            resolver=lambda human, *_: getFriends(human),
        ),
        'appearsIn': GraphQLField(
            GraphQLList(episodeEnum),
            description='Which movies they appear in.',
        ),
        'homePlanet': GraphQLField(
            GraphQLString,
            description='The home planet of the human, or null if unknown.',
        )
    },
    interfaces=[characterInterface]
)

droidType = GraphQLObjectType(
    'Droid',
    description='A mechanical creature in the Star Wars universe.',
    fields=lambda: {
        'id': GraphQLField(
            GraphQLNonNull(GraphQLString),
            description='The id of the droid.',
        ),
        'name': GraphQLField(
            GraphQLString,
            description='The name of the droid.',
        ),
        'friends': GraphQLField(
            GraphQLList(characterInterface),
            description='The friends of the droid, or an empty list if they have none.',
            resolver=lambda droid, *_: getFriends(droid),
        ),
        'appearsIn': GraphQLField(
            GraphQLList(episodeEnum),
            description='Which movies they appear in.',
        ),
        'primaryFunction': GraphQLField(
            GraphQLString,
            description='The primary function of the droid.',
        )
    },
    interfaces=[characterInterface]
)

queryType = GraphQLObjectType(
    'Query',
    fields=lambda: {
        'hero': GraphQLField(
            characterInterface,
            args={
                'episode': GraphQLArgument(
                    description='If omitted, returns the hero of the whole saga. If '
                                'provided, returns the hero of that particular episode.',
                    type=episodeEnum,
                )
            },
            resolver=lambda root, args, *_: getHero(args.get('episode')),
        ),
        'human': GraphQLField(
            humanType,
            args={
                'id': GraphQLArgument(
                    description='id of the human',
                    type=GraphQLNonNull(GraphQLString),
                )
            },
            resolver=lambda root, args, *_: getHuman(args['id']),
        ),
        'droid': GraphQLField(
            droidType,
            args={
                'id': GraphQLArgument(
                    description='id of the droid',
                    type=GraphQLNonNull(GraphQLString),
                )
            },
            resolver=lambda root, args, *_: getDroid(args['id']),
        ),
    }
)

StarWarsSchema = GraphQLSchema(query=queryType, types=[humanType, droidType])
