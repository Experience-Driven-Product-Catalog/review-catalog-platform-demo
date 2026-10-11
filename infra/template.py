"""CloudFormation: two streaming Lambdas, REST API, read-only catalog access."""


def template(bucket, code_key, catalog_key, catalog_sha, code_sha, origin):
    sub = lambda s: {"Fn::Sub": s}
    ref = lambda s: {"Ref": s}
    get = lambda s, a: {"Fn::GetAtt": [s, a]}
    resources = {
        "AuditBucket": {
            "Type": "AWS::S3::Bucket",
            "DeletionPolicy": "Retain",
            "UpdateReplacePolicy": "Retain",
            "Properties": {
                "BucketName": sub(
                    "review-catalog-demo-audit-${AWS::AccountId}-${AWS::Region}"
                ),
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                },
                "OwnershipControls": {
                    "Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]
                },
                "BucketEncryption": {
                    "ServerSideEncryptionConfiguration": [
                        {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                    ]
                },
                "LifecycleConfiguration": {
                    "Rules": [
                        {
                            "Id": "ExpireAuditAfter90Days",
                            "Status": "Enabled",
                            "Prefix": "audit/",
                            "ExpirationInDays": 90,
                            "AbortIncompleteMultipartUpload": {
                                "DaysAfterInitiation": 1
                            },
                        }
                    ]
                },
            },
        },
        "AuditBucketPolicy": {
            "Type": "AWS::S3::BucketPolicy",
            "Properties": {
                "Bucket": ref("AuditBucket"),
                "PolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "DenyInsecureTransport",
                            "Effect": "Deny",
                            "Principal": "*",
                            "Action": "s3:*",
                            "Resource": [
                                get("AuditBucket", "Arn"),
                                sub("${AuditBucket.Arn}/*"),
                            ],
                            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                        },
                        {
                            "Sid": "RequireCreateOnlyWrites",
                            "Effect": "Deny",
                            "Principal": "*",
                            "Action": "s3:PutObject",
                            "Resource": sub("${AuditBucket.Arn}/audit/*"),
                            "Condition": {"Null": {"s3:if-none-match": "true"}},
                        },
                    ],
                },
            },
        },
    }
    for kind in ["Report", "Chat"]:
        name = "review-catalog-platform-demo-" + kind.lower()
        resources[kind + "Log"] = {
            "Type": "AWS::Logs::LogGroup",
            "Properties": {"LogGroupName": "/aws/lambda/" + name, "RetentionInDays": 7},
        }
        resources[kind + "Role"] = {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "lambda.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "Policies": [
                    {
                        "PolicyName": "CatalogAuditAndRuntimeLogs",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["s3:PutObject"],
                                    "Resource": sub(
                                        "${AuditBucket.Arn}/audit/v1/"
                                        + kind.lower()
                                        + "/*"
                                    ),
                                },
                                {
                                    "Effect": "Allow",
                                    "Action": ["s3:GetObject"],
                                    "Resource": f"arn:aws:s3:::{bucket}/{catalog_key}",
                                },
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "logs:CreateLogStream",
                                        "logs:PutLogEvents",
                                    ],
                                    "Resource": get(kind + "Log", "Arn"),
                                },
                            ],
                        },
                    }
                ],
            },
        }
        resources[kind + "Function"] = {
            "Type": "AWS::Lambda::Function",
            "Properties": {
                "FunctionName": name,
                "Runtime": "python3.12",
                "Architectures": ["x86_64"],
                "Handler": "run.sh",
                "Role": get(kind + "Role", "Arn"),
                "MemorySize": 512,
                "Timeout": 300,
                "Layers": [
                    sub(
                        "arn:aws:lambda:${AWS::Region}:753240598075:layer:LambdaAdapterLayerX86:30"
                    )
                ],
                "Code": {"S3Bucket": bucket, "S3Key": code_key},
                "Environment": {
                    "Variables": {
                        "SERVICE": kind.lower(),
                        "AUDIT_BUCKET": ref("AuditBucket"),
                        "AWS_LAMBDA_EXEC_WRAPPER": "/opt/bootstrap",
                        "AWS_LWA_INVOKE_MODE": "response_stream",
                        "AWS_LWA_READINESS_CHECK_PATH": "/health",
                        "AWS_LWA_ENABLE_COMPRESSION": "false",
                        "PORT": "8000",
                        "CATALOG_BUCKET": bucket,
                        "CATALOG_KEY": catalog_key,
                        "CATALOG_SHA256": catalog_sha,
                        "OPENAI_API_KEY": ref("OpenAIKey"),
                        "SESSION_SIGNING_SECRET": ref("SessionSecret"),
                        "EXTRACTION_MODEL": "gpt-6-luna",
                        "EXTRACTION_REASONING": "high",
                        "ANSWER_MODEL": "gpt-6.1-sol",
                        "ANSWER_REASONING": "medium",
                        "ALLOWED_ORIGINS": origin,
                    }
                },
            },
        }
    resources["Api"] = {
        "Type": "AWS::ApiGateway::RestApi",
        "Properties": {
            "Name": "review-catalog-platform-demo",
            "EndpointConfiguration": {"Types": ["REGIONAL"]},
            "DisableExecuteApiEndpoint": False,
        },
    }
    for kind in ["Report", "Chat"]:
        resources[kind + "Permission"] = {
            "Type": "AWS::Lambda::Permission",
            "Properties": {
                "Action": "lambda:InvokeFunction",
                "FunctionName": ref(kind + "Function"),
                "Principal": "apigateway.amazonaws.com",
                "SourceArn": sub(
                    "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${Api}/*"
                ),
            },
        }
    method_ids = []
    for route, verb, kind in [
        ("report", "POST", "Report"),
        ("chat", "POST", "Chat"),
        ("catalog", "GET", "Report"),
        ("health", "GET", "Chat"),
    ]:
        rid = route.title() + "Route"
        mid = route.title() + "Method"
        method_ids.extend([mid, rid + "Options"])
        resources[rid] = {
            "Type": "AWS::ApiGateway::Resource",
            "Properties": {
                "RestApiId": ref("Api"),
                "ParentId": get("Api", "RootResourceId"),
                "PathPart": route,
            },
        }
        resources[mid] = {
            "Type": "AWS::ApiGateway::Method",
            "Properties": {
                "RestApiId": ref("Api"),
                "ResourceId": ref(rid),
                "HttpMethod": verb,
                "AuthorizationType": "NONE",
                "Integration": {
                    "Type": "AWS_PROXY",
                    "IntegrationHttpMethod": "POST",
                    "Uri": sub(
                        "arn:aws:apigateway:${AWS::Region}:lambda:path/2021-11-15/functions/${"
                        + kind
                        + "Function.Arn}/response-streaming-invocations"
                    ),
                    "TimeoutInMillis": 300000,
                    "ResponseTransferMode": "STREAM",
                },
            },
        }
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "600",
        }
        resources[rid + "Options"] = {
            "Type": "AWS::ApiGateway::Method",
            "Properties": {
                "RestApiId": ref("Api"),
                "ResourceId": ref(rid),
                "HttpMethod": "OPTIONS",
                "AuthorizationType": "NONE",
                "Integration": {
                    "Type": "MOCK",
                    "RequestTemplates": {"application/json": '{"statusCode":200}'},
                    "IntegrationResponses": [
                        {
                            "StatusCode": "200",
                            "ResponseParameters": {
                                "method.response.header." + k: "'" + v + "'"
                                for k, v in headers.items()
                            },
                        }
                    ],
                },
                "MethodResponses": [
                    {
                        "StatusCode": "200",
                        "ResponseParameters": {
                            "method.response.header." + k: True for k in headers
                        },
                    }
                ],
            },
        }
    for code in ["DEFAULT_4XX", "DEFAULT_5XX"]:
        resources["Gateway" + code.replace("_", "")] = {
            "Type": "AWS::ApiGateway::GatewayResponse",
            "Properties": {
                "RestApiId": ref("Api"),
                "ResponseType": code,
                "ResponseParameters": {
                    "gatewayresponse.header.Access-Control-Allow-Origin": "'"
                    + origin
                    + "'"
                },
            },
        }
    deployment = "Deployment" + code_sha[:12]
    resources[deployment] = {
        "Type": "AWS::ApiGateway::Deployment",
        "DependsOn": method_ids,
        "Properties": {"RestApiId": ref("Api")},
    }
    resources["Stage"] = {
        "Type": "AWS::ApiGateway::Stage",
        "Properties": {
            "RestApiId": ref("Api"),
            "DeploymentId": ref(deployment),
            "StageName": "prod",
            "MethodSettings": [
                {
                    "ResourcePath": "/*",
                    "HttpMethod": "*",
                    "ThrottlingBurstLimit": 3,
                    "ThrottlingRateLimit": 1,
                    "DataTraceEnabled": False,
                    "LoggingLevel": "OFF",
                    "MetricsEnabled": False,
                }
            ],
        },
    }
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Fixed monitor catalog with private 90-day S3 security records; no EC2 or database server.",
        "Parameters": {
            "OpenAIKey": {"Type": "String", "NoEcho": True},
            "SessionSecret": {"Type": "String", "NoEcho": True},
        },
        "Resources": resources,
        "Outputs": {
            "ApiUrl": {
                "Value": sub(
                    "https://${Api}.execute-api.${AWS::Region}.amazonaws.com/prod"
                )
            },
            "CatalogBucket": {"Value": bucket},
            "AuditBucket": {"Value": ref("AuditBucket")},
            "ReportFunction": {"Value": ref("ReportFunction")},
            "ChatFunction": {"Value": ref("ChatFunction")},
        },
    }
