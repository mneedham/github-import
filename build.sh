#!/bin/bash

lambda_name=${1:-CommunityGraphGitHubImport}
folder=lambda
file=${lambda_name}.zip

rm -rf $folder $file
mkdir -p $folder
echo $'[install]\nprefix=' > $folder/setup.cfg
for lib in "requests neo4j-driver"; do
   pip2.7 install $lib -t $folder
done
cp ${lambda_name}.py $folder
cd $folder; zip -r ../$file .; cd ..

aws s3 cp $file s3://devrel-lambda-functions/