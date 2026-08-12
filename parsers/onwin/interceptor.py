class OnwinInterceptor:

    def attach(self, page):

        def handle_response(response):

            print(response.url)

        page.on("response", handle_response)