import logging
from typing import Any, Iterable, List, Optional, Tuple

from ..utils.math import calc_norm
from .base import BaseModel
from .internal.lightfm_wrapper import LightFMWrapper

from scipy import sparse
from scipy.sparse import csr_matrix
import numpy as np
import implicit.cpu.topk as implicit

class LightFM(BaseModel):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.epochs = kwargs.get("epochs", 10)
        self.n_threads = kwargs.get("n_threads", 1)
        self.model = LightFMWrapper(**kwargs)
        self.recorded_user_ids = set()
        self.recorded_item_ids = set()

    def fit(self, interactions: Iterable[Tuple[Any, Any, float, float]], update_interaction: bool=False) -> None:
        item_id_set, user_id_set = set(), set()
        for user, item, tstamp, rating in interactions:
            try:
                user_id = self.user_ids.identify(user)
                item_id = self.item_ids.identify(item)
                self.interactions.add_interaction(user_id, item_id, tstamp, rating, upsert=update_interaction)
                item_id_set.add(item_id)
                user_id_set.add(user_id)
            except Exception as e:
                logging.warning(f"Error processing interaction: {e}")
                continue

        item_ids = list(item_id_set)
        user_ids = list(user_id_set)
        ui_coo = self.interactions.to_coo(select_users=user_ids, select_items=item_ids)
        num_users, num_items = ui_coo.shape
        user_features = self._create_user_features(num_users, user_ids=user_ids)
        item_features = self._create_item_features(num_items, item_ids=item_ids)
        sampled_weights = None if self.model.loss == "warp-kos" else ui_coo

        self.model.fit_partial(ui_coo, user_features, item_features, sample_weight=sampled_weights, epochs=self.epochs, num_threads=self.n_threads)

    def _record_interactions(self, user_id: int, item_id: int, tstamp: float, rating: float) -> None:
        self.recorded_user_ids.add(user_id)
        self.recorded_item_ids.add(item_id)

    def _fit_recorded(self, parallel: bool=False, progress_bar: bool=True) -> None:
        user_ids = list(self.recorded_user_ids)
        item_ids = list(self.recorded_item_ids)
        ui_coo = self.interactions.to_coo(select_users=user_ids, select_items=item_ids)
        num_users, num_items = ui_coo.shape
        user_features = self._create_user_features(num_users, user_ids=user_ids)
        item_features = self._create_item_features(num_items, item_ids=item_ids)
        sampled_weights = None if self.model.loss == "warp-kos" else ui_coo
        self.model.fit_partial(ui_coo, user_features, item_features, sample_weight=sampled_weights, epochs=self.epochs, num_threads=self.n_threads)

        # Clear recorded user and item IDs
        self.recorded_user_ids.clear()
        self.recorded_item_ids.clear()

    def bulk_fit(self, parallel: bool=False, progress_bar: bool=True) -> None:
        ui_coo = self.interactions.to_coo()
        num_users, num_items = ui_coo.shape
        user_features = self._create_user_features(num_users)
        item_features = self._create_item_features(num_items)
        sampled_weights = None if self.model.loss == "warp-kos" else ui_coo
        self.model.fit_partial(ui_coo, user_features, item_features, sample_weight=sampled_weights, epochs=self.epochs, num_threads=self.n_threads)

    def _recommend(self, user_id: int, top_k: int = 10, filter_interacted: bool = True) -> List[int]:
        num_users, num_items = self.interactions.shape
        user_features = self._create_user_features(num_users=num_users, user_ids=[user_id])
        item_features = self._create_item_features(num_items)

        user_biases, user_embeddings = self.model.get_user_representations(user_features)
        # Note np.ones for dot product with item biases
        user_vector = np.hstack((user_biases[:, np.newaxis], np.ones((user_biases.size, 1)), user_embeddings), dtype=np.float32)
        item_biases, item_embeddings = self.model.get_item_representations(item_features)
        # Note np.ones for dot product with user biases
        item_vector = np.hstack((np.ones((item_biases.size, 1)), item_biases[:, np.newaxis], item_embeddings), dtype=np.float32)

        filter_items = None
        if filter_interacted:
            ui_csr = self.interactions.to_csr(select_users=[user_id])
            filter_items = ui_csr[user_id:].indices

        ids, scores = implicit.topk(items=item_vector, query=user_vector, k=top_k, filter_items=filter_items, num_threads=self.n_threads)
        ids = ids.ravel()
        scores = scores.ravel()

        # implicit assigns negative infinity to the scores to be fitered out
        # see https://github.com/benfred/implicit/blob/v0.7.2/implicit/cpu/topk.pyx#L54
        # the largest possible negative finite value in float32, which is approximately -3.4028235e+38.
        min_score = -np.finfo(np.float32).max
        # remove ids less than or equal to min_score
        for i in range(len(ids)):
            if scores[i] <= min_score:
                ids = ids[:i]
                break

        # query_norm = calc_norm(user_vector)
        # scores = scores.ravel() / query_norm

        return ids.tolist() # ndarray to list

    def _similar_items(self, query_item_id: int, top_k: int = 10) -> List[int]:
        _, num_items = self.interactions.shape

        query_features = self._create_item_features(num_items=num_items, item_ids=[query_item_id])
        target_features = self._create_item_features(num_items=num_items)

        query_biases, query_embeddings = self.model.get_item_representations(query_features)
        query_vector = np.hstack((query_biases[:, np.newaxis], query_embeddings), dtype=np.float32)

        target_biases, target_embeddings = self.model.get_item_representations(target_features)
        target_vector = np.hstack((target_biases[:, np.newaxis], target_embeddings), dtype=np.float32)
        target_norm = calc_norm(target_vector)

        ids, scores = implicit.topk(items=target_vector, query=query_vector, k=top_k, item_norms=target_norm, filter_items=np.array([query_item_id], dtype="int32"), num_threads=self.n_threads)
        ids = ids.ravel()
        scores = scores.ravel()

        # implicit assigns negative infinity to the scores to be fitered out
        # see https://github.com/benfred/implicit/blob/v0.7.2/implicit/cpu/topk.pyx#L54
        # the largest possible negative finite value in float32, which is approximately -3.4028235e+38.
        min_score = -np.finfo(np.float32).max
        # remove ids less than or equal to min_score
        for i in range(len(ids)):
            if scores[i] <= min_score:
                ids = ids[:i]
                break

        # query_norm = calc_norm(query_vector)
        # scores = scores.ravel() / query_norm

        # exclude the query item itself
        return ids[ids != query_item_id].tolist()

    def _create_user_features(self, num_users: int, user_ids: Optional[List[int]]=None) -> csr_matrix:
        """
        Create user features matrix for the given users.

        Parameters:
            num_users (int): Number of users in the dataset.
            user_ids (Optional[List[int]]): List of User IDs to create the user features matrix for.
        Returns:
            csr_matrix: User features matrix of shape (num_users, num_users + num_features) for the given users.
        """
        user_features = self.feature_store.build_user_features_matrix(user_ids, num_users=num_users)  # Shape: (len(user_ids), num_features)

        # Create user identity matrix of shape (len(user_ids), num_users) for the given users
        if user_ids is None:
            user_identity = sparse.identity(num_users, dtype="float32", format="csr")
        else:
            rows = list(range(len(user_ids)))
            cols = user_ids
            data = [1] * len(user_ids)
            user_identity = csr_matrix((data, (rows, cols)), dtype="float32", shape=(num_users, self.interactions.shape[0]))

        if user_features is None:
            return user_identity
        else:
            return sparse.hstack((user_identity, user_features), format="csr")

    def _create_item_features(self, num_items: int, item_ids: Optional[List[int]]=None) -> csr_matrix:
        """
        Create item features matrix for the given items.

        Parameters:
            num_items (int): Number of items in the dataset
            item_ids (Optional[List[int]]): List of Item IDs to create the item features matrix for.
        Returns:
            csr_matrix: Item features matrix of shape (num_items, num_items + num_features) for the given items.
        """

        item_features = self.feature_store.build_item_features_matrix(item_ids, num_items=num_items)

        # Create item identity matrix of shape (len(item_ids), num_items) for the given items
        if item_ids is None:
            item_identity = sparse.identity(num_items, dtype="float32", format="csr")
        else:
            rows = list(range(len(item_ids)))
            cols = item_ids
            data = [1] * len(item_ids)
            item_identity = csr_matrix((data, (rows, cols)), dtype="float32", shape=(num_items, self.interactions.shape[1]))

        if item_features is None:
            return item_identity
        else:
            return sparse.hstack((item_identity, item_features), format="csr")
