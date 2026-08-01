class CDPCommands:

    @staticmethod
    def create_target(client):

        response = client.send(
            "Target.createTarget",
            {
                "url": "about:blank"
            }
        )

        return response["result"]["targetId"]

    @staticmethod
    def attach_target(client, target_id):

        response = client.send(
            "Target.attachToTarget",
            {
                "targetId": target_id,
                "flatten": True
            }
        )

        return response["result"]["sessionId"]