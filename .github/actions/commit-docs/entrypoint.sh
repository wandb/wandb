  
#!/bin/sh
set -eu

# Set up .netrc file with GitHub credentials
git_setup() {
  cat <<- EOF > $HOME/.netrc
        machine github.com
        login $GITHUB_ACTOR
        password $GITHUB_TOKEN
        machine api.github.com
        login $GITHUB_ACTOR
        password $GITHUB_TOKEN
EOF
    chmod 600 $HOME/.netrc

    git config --global user.email "actions@github.com"
    git config --global user.name "Add & Commit GitHub Action"
}

add() {
    if $INPUT_FORCE 
    then find $INPUT_PATH -name "$INPUT_PATTERN" | while read x; do git add -f $x; done
    else find $INPUT_PATH -name "$INPUT_PATTERN" | while read x; do git add $x; done
    fi
}

# This is needed to make the check work for untracked files
echo "Staging files in commit path..."
git_setup
git clone $INPUT_REPO doc_repo
cd doc_repo
mkdir -p library/reference
rm -rf library/reference/*
cp ../generated_docs/* library/reference/
git add library/reference/*

#add

echo "Checking for uncommitted changes in the git working tree..."
# This section only runs if there have been file changes
if ! git diff --cached --exit-code
then

    # Switch to branch from current Workflow run
    echo "Creating and switching branch..."
    git branch "${GITHUB_REF:11}"
    git checkout "${GITHUB_REF:11}"
    
    git status
    echo "Status was called"
    #echo "Adding files..."
    #add

    #echo "Creating commit..."
    #git commit -m "$INPUT_MESSAGE" --author="$INPUT_AUTHOR_NAME <$INPUT_AUTHOR_EMAIL>"

    #echo "Pushing to repo..."
    #git push --set-upstream origin "${GITHUB_REF:11}"
else
    echo "Working tree clean. Nothing to commit."
fi