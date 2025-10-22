import boto3

lambda_client = boto3.client('lambda')

def lambda_handler(event, context):
    response = lambda_client.invoke(
        FunctionName='target_lambda_name',
        InvocationType='RequestResponse',  # or 'Event' for async
        Payload=b'{"key":"value"}'
    )
    
    result = response['Payload'].read().decode('utf-8')
    return result
