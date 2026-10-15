'use strict';
var token = '%[a-f0-9]{2}';
var singleMatcher = new RegExp('(' + token + ')|([^%]+?)', 'gi');
var multiMatcher = new RegExp('(' + token + ')+', 'gi');

function decodeComponents(components, split) {
	try {
		return [decodeURIComponent(components.join(''))];
	} catch (err) {
		if (components.length === 1) {
			return components;
		}
		split = split || 1;
		var left = components.slice(0, split);
		var right = components.slice(split);
		return Array.prototype.concat.call([], decodeComponents(left), decodeComponents(right));
	}
}

function decode(input) {
	try {
		return decodeURIComponent(input);
	} catch (err) {
		var tokens = input.match(singleMatcher) || [];
		for (var i = 1; i < tokens.length; i++) {
			input = decodeComponents(tokens, i).join('');
			tokens = input.match(singleMatcher) || [];
		}
		return input;
	}
}

function customDecodeUriComponent(input) {
	if (typeof input !== 'string') {
		throw new TypeError('Expected `encodedURI` to be of type `string`, got `' + typeof input + '`');
	}
	try {
		return decodeURIComponent(input);
	} catch (err) {
		var replacement = input.replace(multiMatcher, decode);
		return replacement;
	}
}

module.exports = customDecodeUriComponent;
module.exports.default = customDecodeUriComponent;
