from collections import defaultdict
from typing import List, Optional, Any
import time, math

from scipy.sparse import csr_matrix, csc_matrix

class UserItemInteractions:
    def __init__(self, min_value: int = -5, max_value: int = 10, decay_in_days: Optional[int] = None, **kwargs: Any) -> None:
        """
        Initializes the UserItemInteractions class.

        Args:
            min_value (int): Minimum allowable value for interactions.
            max_value (int): Maximum allowable value for interactions.
            decay_rate (Optional[float]): Rate at which interactions decay over time.
                                          If None, no decay is applied.
        """
        # Store interactions as a dictionary of dictionaries in shape {user_id: {item_id: (value, timestamp)}}
        self.interactions: defaultdict[int, dict[int, tuple[float, float]]] = defaultdict(dict)
        self.empty = {}
        self.all_item_ids = set()
        assert max_value > min_value, f"max_value should be greater than min_value {max_value} > {min_value}"
        self.min_value = min_value
        self.max_value = max_value
        if decay_in_days is None:
            self.decay_rate = None
        else:
            # Follow the way in "Time Weight collaborative filtering" in the paper
            # Half-life decay in time: decay_rate = 1 - ln(2) / decay_in_days
            # https://dl.acm.org/doi/10.1145/1099554.1099689
            self.decay_rate = 1.0 - (math.log(2) / decay_in_days)

    def get_decay_rate(self) -> Optional[float]:
        """
        Retrieves the decay rate for interactions.

        Returns:
            Optional[float]: The decay rate for interactions.
        """
        return self.decay_rate

    def set_decay_rate(self, decay_rate: Optional[float]) -> None:
        """
        Sets the decay rate for interactions.

        Args:
            decay_rate (Optional[float]): The decay rate for interactions.
        """
        self.decay_rate = decay_rate

    def _apply_decay(self, value: float, last_timestamp: float) -> float:
        """
        Applies decay to a given value based on the elapsed time since the last interaction.

        Args:
            value (float): The original interaction value.
            last_timestamp (float): The timestamp of the last interaction.

        Returns:
            float: The decayed interaction value.
        """
        if self.decay_rate is None:
            return value

        elapsed_seconds = time.time() - last_timestamp
        elapsed_days = elapsed_seconds / 86400.0

        return value * self.decay_rate ** elapsed_days # approximated exponential decay in time e^(-ln(2)/decay_in_days * elapsed_days)

    def add_interaction(self, user_id: int, item_id: int, tstamp: float, delta: float = 1.0, upsert: bool = False) -> None:
        """
        Adds or updates an interaction count for a user-item pair.

        Args:
            user_id (int): ID of the user.
            item_id (int): ID of the item.
            delta (float): Change in interaction count (default is 1.0).
            upsert (bool): Flag to update the interaction count if it already exists (default is False).
        """
        if upsert:
            self.interactions[user_id][item_id] = (delta, tstamp)
        else:
            current = self.get_user_item_rating(user_id, item_id, default_rating=0.0)
            new_value = current + delta

            # Clip the new value within the defined bounds
            new_value = max(self.min_value, min(new_value, self.max_value))

            # Store the updated value with the current timestamp
            self.interactions[user_id][item_id] = (new_value, tstamp)
        self.all_item_ids.add(item_id)

    def get_user_item_rating(self, user_id: int, item_id: int, default_rating: float = 0.0) -> float:
        """
        Retrieves the interaction count for a specific user-item pair, applying decay if necessary.

        Args:
            user_id (int): ID of the user.
            item_id (int): ID of the item.
            default_rating (float): Default rating to return if no interaction exists (default is 0.0).

        Returns:
            float: The decayed interaction value for the specified user-item pair.
        """
        current, last_timestamp = self.interactions[user_id].get(item_id, (default_rating, time.time()))
        if current == default_rating:
            return default_rating  # Return default if no interaction exists
        return self._apply_decay(current, last_timestamp)

    def get_user_items(self, user_id: int, n_recent: Optional[int] = None) -> List[int]:
        """
        Retrieves the dictionary of item IDs and their interaction counts for a given user,
        applying decay to each interaction.

        Args:
            user_id (int): ID of the user.
            n_recent (Optional[int]): Number of most recent items to consider (default is None).

        Returns:
            List[int]: List of item IDs that the user has interacted with.
        """
        # use top-k recent items for the user
        if n_recent is not None and len(self.interactions) > n_recent:
            # sort by timestamp in descending order
            return [item_id for item_id, _ in sorted(self.interactions.get(user_id, self.empty).items(), key=lambda x: x[1][1], reverse=True)[:n_recent]]
        else:
            return list(self.interactions.get(user_id, self.empty).keys())

    def get_all_item_ids(self) -> List[int]:
        """
        Retrieves a list of all unique item IDs.

        Returns:
            List[int]: List of unique item IDs.
        """
        return list(self.all_item_ids)

    def get_all_users(self) -> List[int]:
        """
        Retrieves a list of all user IDs.

        Returns:
            List[int]: List of user IDs.
        """
        return list(self.interactions.keys())

    def get_all_non_interacted_items(self, user_id: int) -> List[int]:
        """
        Retrieves a list of all items a user has not interacted with.

        Args:
            user_id (int): ID of the user.

        Returns:
            List[int]: List of item IDs the user has not interacted with.
        """
        interacted_items = set(self.get_user_items(user_id))
        return [item_id for item_id in self.all_item_ids if item_id not in interacted_items]

    def get_all_non_negative_items(self, user_id: int) -> List[int]:
        """
        Retrieves a list of all items with non-negative interaction counts, applying decay to each interaction.

        Args:
            user_id (int): ID of the user.

        Returns:
            List[int]: List of item IDs with non-negative interaction counts.
        """
        # Return all items with non-negative interaction counts after applying decay
        return [item_id for item_id in self.all_item_ids
                if self.get_user_item_rating(user_id, item_id, default_rating=0.0) >= 0.0]

    def to_csr(self) -> csr_matrix:
        rows, cols, data = [], [], []
        max_row, max_col = 0, 0

        for user, inner_dict in self.interactions.items():
            for item, (rating, tstamp) in inner_dict.items():
                rows.append(user)
                cols.append(item)
                data.append(self._apply_decay(rating, tstamp))
                max_row = max(max_row, user)
                max_col = max(max_col, item)

        # Create the csr_matrix
        return csr_matrix((data, (rows, cols)), shape=(max_row + 1, max_col + 1))

    def to_csc(self) -> csc_matrix:
        rows, cols, data = [], [], []
        max_row, max_col = 0, 0

        for user, inner_dict in self.interactions.items():
            for item, (rating, tstamp) in inner_dict.items():
                rows.append(user)
                cols.append(item)
                data.append(self._apply_decay(rating, tstamp))
                max_row = max(max_row, user)
                max_col = max(max_col, item)

        # Create the csc_matrix
        return csc_matrix((data, (rows, cols)), shape=(max_row + 1, max_col + 1))
