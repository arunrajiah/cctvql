import {
	IExecuteFunctions,
	IHttpRequestOptions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	NodeOperationError,
} from 'n8n-workflow';

export class CctvqlQuery implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'cctvQL Query',
		name: 'cctvqlQuery',
		icon: 'file:cctvql.svg',
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["query"]}}',
		description: 'Ask cctvQL a natural language question about your cameras',
		defaults: { name: 'cctvQL Query' },
		inputs: ['main'],
		outputs: ['main'],
		credentials: [{ name: 'cctvqlApi', required: true }],
		properties: [
			{
				displayName: 'Query',
				name: 'query',
				type: 'string',
				default: '',
				placeholder: 'Were there any people at the front door last night?',
				description: 'Natural language question to ask cctvQL. Supports expressions.',
				required: true,
			},
			{
				displayName: 'Session ID',
				name: 'sessionId',
				type: 'string',
				default: 'n8n',
				description: 'Session ID for multi-turn conversations. Use a unique value per workflow.',
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];
		const credentials = await this.getCredentials('cctvqlApi');

		const baseUrl = `${credentials.protocol}://${credentials.host}:${credentials.port}`;
		const headers: Record<string, string> = { 'Content-Type': 'application/json' };
		if (credentials.apiKey) headers['X-API-Key'] = credentials.apiKey as string;

		for (let i = 0; i < items.length; i++) {
			const query = this.getNodeParameter('query', i) as string;
			const sessionId = this.getNodeParameter('sessionId', i) as string;

			if (!query.trim()) {
				throw new NodeOperationError(this.getNode(), 'Query cannot be empty', { itemIndex: i });
			}

			const options: IHttpRequestOptions = {
				method: 'POST',
				url: `${baseUrl}/query`,
				headers,
				body: { query, session_id: sessionId },
				json: true,
			};

			const data = await this.helpers.httpRequest(options);

			returnData.push({
				json: {
					answer: data.answer ?? '',
					intent: data.intent ?? '',
					session_id: data.session_id ?? sessionId,
					...data,
				},
				pairedItem: { item: i },
			});
		}

		return [returnData];
	}
}
